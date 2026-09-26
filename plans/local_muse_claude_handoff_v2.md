# Local Muse — Claude Handoff Plan (v2)

This document is the authoritative build spec for **Local Muse**. It supersedes v1. Where this document and any earlier notes disagree, this document wins.

Read it fully before writing code. Section 26 tells you where to start.

---

# 1. Project Goal

Build **Local Muse**, a local-first personal AI agent inspired by Meta Muse, running on a single Mac.

This is **not OpenMuse** and must **not use OpenComputer**.

Capabilities (final state):

- persistent conversations
- long-running background tasks
- topic/subagent delegation (bounded, not recursive)
- local model inference
- browser automation (research + authenticated contexts)
- code/shell execution in restricted Docker sandboxes
- durable workflows
- scheduled goals
- human approvals bound to exact action contents
- realtime updates to web/mobile clients
- phone access over Tailscale
- Telegram alerts and lightweight remote control
- persistent, editable memory
- auditability
- hard separation between model intent and privileged execution

Target machine:

- Apple M1 Max, 64 GB unified memory, macOS
- Docker Desktop
- Ollama (native, Metal-accelerated)

Explicitly out of scope for v1: see Section 21.

---

# 2. Core Principles

## 2.1 Intelligence is not authority

The model may *want* to do things. It never *has* the permission, credentials, network authority, or host access to do them.

```text
User
  ↓
Temporal Workflow
  ↓
PydanticAI Agent
  ↓
ToolIntent            (model output: tool name + args, nothing else)
  ↓
Trusted Tool Registry (validates args, assigns risk/side-effect/permissions)
  ↓
ActionProposal        (trusted, immutable)
  ↓
PolicyEngine
  ↓
ALLOW / DENY / REQUIRE_APPROVAL
  ↓
Trusted Executor
  ↓
Result returned to agent
```

**The model never populates risk, side_effect, required_permissions, or data_classification.** Those come from the registry. A model that could classify its own actions could classify a wire transfer as harmless.

## 2.2 Every tool goes through the policy boundary from the first commit

There is no phase where `Agent → Tool` exists without `→ Registry → PolicyEngine →` in between. Early policy returns `ALLOW` for everything. Tightening policy later must never require touching the tool stack.

## 2.3 Modular monolith, except where privilege separation demands otherwise

Keep clean module boundaries for: AgentRuntime, ToolRegistry, PolicyEngine, BrowserController, SandboxClient, MemoryService, NotificationService, RealtimePublisher, ModelProvider.

Do not split these into services for tidiness. Split **only** for privilege separation. In v1 there is exactly one such split: **sandboxd** (Section 10), because it holds the Docker socket.

## 2.4 Local-first

```text
LOCAL_MUSE_MODE=offline   # local model only
LOCAL_MUSE_MODE=hybrid    # local by default, escalate specific workloads to cloud
LOCAL_MUSE_MODE=cloud     # cloud model primary
```

v1 implements `offline`. Keep the provider abstraction clean so `hybrid` is a config change, not a refactor. Expect that a 30B-class local model will be unreliable at long multi-step tool loops; design the loop to tolerate malformed output, and expect `hybrid` to arrive sooner than "eventually."

## 2.5 Durability lives in Temporal + Postgres, never in memory, never in Centrifugo

- Temporal owns workflow execution state.
- Postgres owns application state.
- Centrifugo owns nothing. It is ephemeral fanout.

---

# 3. Topology

```text
                    iPhone PWA          Mac browser
                         │                   │
                         └───── Tailscale ───┘
                                     │
┌────────────────────────────────────┼─────────────────────────────────────┐
│ MACBOOK                            │                                     │
│                                    ▼                                     │
│  Native macOS ─────────────────────────────────────────────────────────  │
│    Ollama  (OpenAI-compatible HTTP, host.docker.internal:11434)         │
│                                                                          │
│  Docker Compose ──────────────────────────────────────────────────────   │
│    web (Vite React PWA, static)                                         │
│    backend (FastAPI)  ──── postgres                                      │
│         │             ──── centrifugo                                    │
│         │             ──── temporal + temporal-ui                        │
│         ▼                                                                │
│    worker (Temporal worker + PydanticAI)                                 │
│         │  ToolIntent → Registry → ActionProposal → PolicyEngine         │
│         ├── BrowserController → Playwright/Chromium (in worker)          │
│         ├── HTTP tools                                                   │
│         └── SandboxClient ──(internal network only)──▶ sandboxd          │
│                                                           │ docker.sock  │
│                                                           ▼              │
│                                             restricted sandbox containers│
│                                             no network / no secrets      │
│                                                                          │
│    telegram poller (in backend; outbound long-polling, no inbound port)  │
└──────────────────────────────────────────────────────────────────────────┘
```

Only `sandboxd` has the Docker socket. The worker does not. The backend does not.

---

# 4. Technology Choices

| Concern | Choice | Notes |
|---|---|---|
| Frontend | Vite + React + TypeScript, PWA | Not Next.js. Private single-user app; no SSR/SEO needs. Served as static files by nginx or by FastAPI. |
| Backend | Python 3.12+, FastAPI | HTTP API, auth, Temporal client, Centrifugo publisher, Telegram poller, model gateway |
| Agent framework | PydanticAI | Typed deps, typed tools, structured outputs, `TemporalAgent` |
| Durable runtime | Temporal (self-hosted, `temporalio/auto-setup`) | Core dependency from day one |
| App state | PostgreSQL 16 | Application source of truth. Temporal uses a separate database in the same instance. |
| Realtime | Centrifugo | Fanout only. Small messages only. |
| Local model | Ollama, native macOS | Ollama uses llama.cpp/Metal with GGUF models. It is **not** MLX. MLX is a separate runtime (`mlx_lm.server`) and may be benchmarked later behind the same provider interface. |
| Browser | Playwright + Chromium, inside the worker container | Narrow API only. Never expose page/CDP. |
| Sandbox control | `sandboxd` — tiny Python service, own container, Docker socket mounted | See Section 10 |
| Phone access | Tailscale | No port forwarding, no tunnels, no public ingress |
| Telegram | Long polling (`getUpdates`) | Outbound only. No webhook in v1. |

---

# 5. Trust Boundaries and Threat Model

Write `docs/threat-model.md` from this section before implementation.

## 5.1 Trust zones

```text
UNTRUSTED
  - model output (all of it, including tool calls and "reasoning")
  - web page content
  - sandbox contents and sandbox output
  - Telegram inbound messages
  - files downloaded by the browser

TRUSTED (application code we wrote)
  - FastAPI backend
  - Temporal worker (registry, policy, executors, browser controller)
  - sandboxd

PRIVILEGED
  - sandboxd (Docker socket)
  - credential store (backend only)
  - authenticated browser profile (worker only, never sandbox)
```

## 5.2 Threats we design against

1. Prompt injection via web page → model emits harmful ToolIntent. Mitigation: registry classification + policy + approvals; browser click/fill are not READ_ONLY.
2. Compromised worker process → host compromise. Mitigation: worker has no Docker socket, no host mounts, no credentials beyond what its executors need.
3. Sandbox escape. Mitigation: cap_drop ALL, non-root, no-new-privileges, no network, PID/CPU/mem limits, read-only rootfs, only `/workspace` writable.
4. Approval replay / substitution. Mitigation: approval bound to `approval_key` hash of exact action contents.
5. Forged approval request. Mitigation: session auth on FastAPI; Telegram callbacks validated against bot token + allowed `chat_id` + pending action existence.
6. Credential leakage into prompts/memory/sandbox. Mitigation: credential refs only; trusted resolution at execution time; classification bump on authenticated-browser output.
7. Runaway recursion / cost. Mitigation: no recursive subagents; topic depth = 1; concurrency caps; step limits per run.

---

# 6. Tool Intent, Registry, and Action Proposals

## 6.1 What the model emits

```python
class ToolIntent(BaseModel):
    tool: str            # e.g. "browser.click", "sandbox.exec", "gmail.send"
    args: dict[str, Any]
```

Nothing else. No risk field. No permissions field.

## 6.2 Trusted Tool Registry

Each registered tool declares, in code, its classification. Classification may be static or computed from validated args and execution context (e.g. browser context type, target domain).

```python
class ToolSpec(BaseModel):
    name: str
    args_model: type[BaseModel]
    classify: Callable[[BaseModel, ExecContext], Classification]
    executor: Callable[..., Awaitable[ToolResult]]
    retry: RetryPolicy
    idempotent: bool
```

```python
class Classification(BaseModel):
    risk: RiskClass
    side_effect: SideEffectClass
    required_permissions: list[str]
    data_classification: DataClassification
    destination: str | None
```

The registry:

1. looks up `tool` — unknown tool → `DENY`, audit
2. validates `args` against `args_model` — invalid → returned to the model as a tool error, never executed
3. calls `classify(validated_args, ctx)`
4. produces an `ActionProposal`

## 6.3 ActionProposal

```python
class ActionProposal(BaseModel):
    action_id: UUID                 # idempotency key for executors
    approval_key: str               # see Section 8
    actor_id: str                   # "coordinator" | "topic:<id>"
    user_id: UUID
    conversation_id: UUID
    topic_id: UUID | None
    tool: str
    args: dict                      # validated, canonicalized
    risk: RiskClass
    side_effect: SideEffectClass
    required_permissions: list[str]
    data_classification: DataClassification
    destination: str | None
    credential_ref: str | None      # reference only; never the secret
    created_at: datetime
```

Immutable once created. Persisted to `actions` table with the policy decision.

## 6.4 Enums

```text
RiskClass:
  READ_ONLY
  LOCAL_MUTATION
  EXTERNAL_WRITE
  SENSITIVE_EXTERNAL_WRITE
  DESTRUCTIVE

SideEffectClass:
  NONE
  LOCAL_FILE_WRITE
  NETWORK_READ
  NETWORK_WRITE
  MESSAGE_SEND
  REMOTE_UPDATE
  PURCHASE
  DELETE

DataClassification:
  PUBLIC
  PERSONAL
  AUTHENTICATED   # output came from a logged-in session
  SECRET          # must never exist; used only to DENY
```

---

# 7. PolicyEngine

A Python module inside the worker. Not a service.

```python
class PolicyEngine:
    async def evaluate(self, action: ActionProposal, ctx: ExecContext) -> Decision: ...
```

```text
Decision:
  ALLOW
  DENY(reason)
  REQUIRE_APPROVAL(summary_for_human)
```

## 7.1 v1 rules

Rules are evaluated in order; first match wins. Everything else falls to the default.

| Condition | Decision |
|---|---|
| tool not registered | DENY |
| data_classification == SECRET | DENY |
| any host/system action (not a registered tool) | DENY |
| sandbox.* (exec, read, write, list) | ALLOW |
| browser.navigate / snapshot / screenshot / scroll, research context | ALLOW |
| browser.click / fill / press, research context, domain in allowlist | ALLOW |
| browser.click / fill / press, research context, domain not in allowlist | REQUIRE_APPROVAL |
| browser.*, authenticated context, any mutation (click/fill/press/download) | REQUIRE_APPROVAL |
| browser.navigate / snapshot, authenticated context | ALLOW, output tagged AUTHENTICATED |
| http.get (public) | ALLOW |
| web.search | ALLOW |
| notify.user (Telegram to owner only) | ALLOW |
| side_effect in {MESSAGE_SEND, REMOTE_UPDATE, PURCHASE, DELETE} | REQUIRE_APPROVAL |
| risk in {EXTERNAL_WRITE, SENSITIVE_EXTERNAL_WRITE, DESTRUCTIVE} | REQUIRE_APPROVAL |
| default (unknown external mutation) | REQUIRE_APPROVAL |

The research-browser domain allowlist starts empty; the user can add domains from the UI. An empty allowlist means every click in research mode requires approval, which is acceptable for Phase 8 and will be tuned.

## 7.2 Policy is context-aware for the browser

`browser.click` on "Expand details" and `browser.click` on "Confirm purchase" are the same tool. Policy cannot know intent from the tool name. So policy keys on: browser context type (research vs authenticated), target domain, and the element's accessible name/role. Heuristic escalation (e.g. accessible name matches `/buy|purchase|confirm|send|submit|pay|delete/i` in authenticated context) → REQUIRE_APPROVAL regardless of allowlist. Document the heuristics; do not pretend they are complete.

---

# 8. Approvals

## 8.1 Approval key

```python
approval_key = sha256(
    canonical_json({
        "tool": proposal.tool,
        "args": proposal.args,           # canonicalized, sorted keys
        "destination": proposal.destination,
        "credential_ref": proposal.credential_ref,
        "user_id": str(proposal.user_id),
    })
).hexdigest()
```

**Do not include** page snapshots, timestamps, model reasoning, or any non-deterministic context in the key. Those are shown to the human as `summary_for_human`; they are not part of identity.

An approval grants exactly one `approval_key`. If the model re-proposes with different args, that is a new approval. A retry of the same action after a transient failure reuses the same `action_id` and `approval_key` and does not re-prompt.

## 8.2 End-to-end flow

```text
1.  Agent emits ToolIntent
2.  Registry → ActionProposal (with approval_key)
3.  PolicyEngine → REQUIRE_APPROVAL
4.  Persist approvals row: status=PENDING, action_id, approval_key, summary
5.  Workflow enters durable wait (Temporal condition on signal/update)
6.  Publish approval.required via Centrifugo
7.  NotificationService sends Telegram message with [Approve] [Deny]
8.  User acts from web/PWA/Telegram
9.  FastAPI (or Telegram poller) validates: session/chat_id, approval exists, still PENDING
10. Persist decision (APPROVED/DENIED, decided_by, decided_at, channel)
11. Send Temporal Update to the waiting workflow
12. Workflow resumes; executor runs with action_id as idempotency key
13. Persist result; publish approval.resolved + tool.completed
14. Agent continues
```

Approval must survive: browser close, API restart, worker restart, laptop reboot, days of delay. Duplicate approvals (double-tap, Telegram retry) must be harmless: second decision on a non-PENDING approval is a no-op.

Approvals expire (default 7 days) → DENIED(expired), workflow notified.

---

# 9. Credentials

The model and the sandbox never receive raw credentials.

```text
credential_ref = "gmail:owner"
```

Trusted executor code resolves the reference at execution time from the backend credential store (encrypted at rest in Postgres with a key from `.env`; v1 acceptable).

Never place secrets in: prompts, model-visible tool args, sandbox env, sandbox workspace, browser-visible frontend state, topic memory, profile memory, Centrifugo messages, logs.

## 9.1 Browser profiles are credentials

The authenticated Chromium profile (cookies, local storage, saved logins) is a credential. It:

- lives on a worker-only named volume
- is never mounted into sandboxes
- is never copied into `/workspace`
- is never described in memory beyond "authenticated session exists for domain X"
- produces outputs (snapshots/screenshots) tagged `AUTHENTICATED`, which policy treats as PERSONAL data for any onward action (e.g. writing them to a sandbox workspace requires approval; sending them anywhere external requires approval)

---

# 10. Sandbox Design

## 10.1 sandboxd

A separate, minimal Python service (FastAPI or plain aiohttp) in its own container. It is the **only** container with `/var/run/docker.sock`.

API (internal, narrow, no arbitrary Docker passthrough):

```text
POST   /sandboxes                      {topic_id}                → {sandbox_id}
POST   /sandboxes/{id}/exec            {cmd, timeout_s, cwd}     → {stdout, stderr, exit_code, truncated}
PUT    /sandboxes/{id}/files/{path}    body                      → ok
GET    /sandboxes/{id}/files/{path}                              → body
GET    /sandboxes/{id}/files?path=     → listing
POST   /sandboxes/{id}/stage           {artifact_id | package}   → ok   (trusted stager, Section 10.4)
DELETE /sandboxes/{id}                 (container destroyed, volume kept)
DELETE /sandboxes/{id}/volume          (explicit, approval-gated)
```

Network isolation: `sandboxd` sits on a dedicated Compose network `sandbox-control`. Only `worker` is also attached. That is the v1 access control. Additionally require a shared bearer token from `.env` so a misconfigured network doesn't silently open it.

sandboxd applies every constraint in 10.2 on container create. Callers cannot override them. There is no "options" passthrough.

## 10.2 Sandbox container constraints (mandatory, enforced by sandboxd)

```text
image: local-muse-sandbox:<pinned>
user: sandbox (uid 10001), non-root
cap_drop: [ALL]
security_opt: [no-new-privileges:true]
read_only: true                      # rootfs
tmpfs: /tmp (size-limited)
volumes: named volume → /workspace (rw)   # nothing else
network_mode: none
pids_limit: 256
cpus: 2
mem_limit: 4g
no docker socket, no host paths, no env secrets
```

Never mount: `/var/run/docker.sock`, `~`, `~/.ssh`, `~/.aws`, `~/Documents`, or any host path.

## 10.3 Lifecycle

```text
container = ephemeral
workspace volume = durable (per topic)
topic memory = Postgres
workflow state = Temporal
```

TopicWorkflow starts → create sandbox → attach `ws-<topic_id>` volume → run → topic pauses → destroy container, keep volume → resume → fresh container, reattach volume. Sandbox and workflow lifetimes are independent.

## 10.4 Dependencies without network

Sandbox has no network, so `pip install` inside it does not work. v1 uses:

- **A. Fat image**: preinstall Python 3.12, numpy, pandas, polars, matplotlib, requests (unused but expected), beautifulsoup4, lxml, pyarrow, openpyxl, jq, ripgrep, git, curl (inert), node LTS. Document the list in `sandbox/Dockerfile`.
- **B. Trusted stager**: `sandbox.stage(artifact_id)` copies an artifact the agent previously obtained via trusted tools (browser download, http.get) into `/workspace/incoming/`. `sandbox.stage_package(name, version)` is out of scope for v1; register the tool name and return a clear "not available" error so the model learns.

Do not give the sandbox outbound network "for convenience."

---

# 11. Browser Design

## 11.1 Two contexts

```text
research       cookie-less, fresh Chromium context per topic, no saved state
authenticated  persistent Chromium profile owned by the user, explicit opt-in per session
```

The agent must request `browser.open_session(context="authenticated")` and that request itself is REQUIRE_APPROVAL.

## 11.2 Exposed tools (the entire browser surface)

```text
browser.open_session(context)
browser.navigate(url)
browser.snapshot()                → accessibility tree, element ids
browser.screenshot()              → stored artifact, id returned
browser.click(element_id)
browser.fill(element_id, text)
browser.press(element_id, key)
browser.scroll(direction)
browser.download(element_id)      → artifact id
browser.close_session()
```

Not exposed, ever: `page.evaluate`, raw CDP, arbitrary JS, raw Playwright objects, cookie access.

Snapshot format:

```json
{ "url": "...", "title": "...", "context": "research",
  "elements": [{ "id": "e42", "role": "button", "name": "Continue", "value": null }] }
```

Element ids are per-snapshot; a click against a stale snapshot returns an error and the model must re-snapshot.

## 11.3 Human takeover

```text
browser.mode ∈ {agent, human}
```

Human takes control → agent browser activities block (Temporal condition wait); publish `browser.mode=human`. Control returns → publish `browser.mode=agent`, agent re-snapshots before continuing. Never simultaneous control.

## 11.4 Frames

Do not push screenshots through Centrifugo. Centrifugo carries:

```json
{ "type": "browser.frame", "session_id": "b17", "frame_version": 412 }
```

The client fetches `GET /browser/{session_id}/frame?v=412` (JPEG) from FastAPI, or subscribes to a dedicated FastAPI WebSocket for the live viewer. Cap frame rate at ~2 fps in v1.

---

# 12. Temporal Design

Write `docs/temporal-design.md` from this section.

## 12.1 Workflows

**ConversationWorkflow** — `workflow_id = conv-<conversation_id>`

- receives user messages via Update (`send_message`) — Update, not Signal, so the client gets an ack/rejection
- invokes coordinator agent
- starts TopicWorkflow children; receives their results via child completion
- tracks pending approvals
- Continue-As-New after N runs or when history > 10k events; carries only ids and a compact state struct, never message content

**TopicWorkflow** — `workflow_id = topic-<topic_id>`, child of conversation

- runs the topic worker agent loop with a max step count (default 60)
- owns one sandbox (optional) and one browser session (optional)
- pauses on approval; survives restarts
- returns a `TopicResult` to the parent
- Continue-As-New if step count grows large

**GoalWorkflow** — `workflow_id = goal-<goal_id>`

- one-shot delay: Temporal timer
- recurring: Temporal Schedule that starts a TopicWorkflow per fire
- "notify when X": recurring TopicWorkflow with a `meaningful_result` predicate; notifies only when the predicate flips
- no Python sleep loops

## 12.2 Signals vs Updates

- Updates: user message, approval decision, takeover on/off, cancel-with-ack. Anything the client needs a synchronous accept/reject for.
- Signals: fire-and-forget notifications between workflows (e.g. topic progress hints to the parent).

## 12.3 Activities

```text
call_model                 (task queue: model-inference, max_concurrent=1)
persist_message
persist_topic_memory
persist_action
publish_realtime_event
send_notification
browser_*                  (one activity per browser tool)
sandbox_*                  (one activity per sandboxd call)
execute_external_action    (approved side effects; idempotent on action_id)
```

Do not go more granular. Each activity is a meaningful retry boundary.

## 12.4 Model concurrency

There is one local model. Do not write a scheduler. Register `call_model` on a dedicated task queue served by a worker with `max_concurrent_activities=1`. Three TopicWorkflows may be logically active; inference serializes automatically; browser I/O, sandbox compute, and timers still overlap.

`call_model` uses heartbeats (every 10 s) and a start-to-close timeout of 10 minutes; a 30B MoE at 4-bit generating a long structured response can take minutes.

## 12.5 Retry policy

Safe to retry: `call_model`, `http.get`, `browser.navigate`, `browser.snapshot`, sandbox reads.

Never blindly retry: anything with side_effect in {MESSAGE_SEND, REMOTE_UPDATE, PURCHASE, DELETE}. `execute_external_action` retries only if the executor is registered `idempotent=True` and uses `action_id` as the idempotency key.

## 12.6 Cancellation

User can cancel a run, topic, goal, browser action, or sandbox job. Cancel propagates via Temporal cancellation; TopicWorkflow's finally block always calls `sandbox.destroy` and `browser.close_session` as non-cancellable cleanup activities.

## 12.7 What lives where

```text
Temporal:  workflow state, timers, waits, child relationships, retries
Postgres:  everything a user can see or edit, and everything the audit needs
Memory:    nothing that must survive a restart
```

---

# 13. PydanticAI Design

```python
@dataclass
class AgentDeps:
    user_id: UUID
    conversation_id: UUID
    topic_id: UUID | None
    memory: MemoryService
    tools: ToolGateway        # the ONLY path to any side effect
```

`ToolGateway.invoke(ToolIntent) -> ToolResult` runs registry → policy → executor. Agents receive the gateway, never the controllers.

Agents: `coordinator` (routes, starts topics, answers directly for small things) and `topic_worker` (executes one objective). No agent may start an agent other than the coordinator starting topic workers. Depth is 1. Max 3 concurrent topics per conversation.

Structured output for every model call. Malformed output → one repair attempt with the validation error, then fail the step and let the workflow decide.

---

# 14. Model Provider

```python
class ModelProvider(Protocol):
    async def complete(self, req: CompletionRequest) -> CompletionResponse: ...
    async def stream(self, req: CompletionRequest) -> AsyncIterator[Delta]: ...
    async def health(self) -> ProviderHealth: ...
```

Providers: `OllamaProvider` (v1), `OpenAICompatibleProvider`, `AnthropicProvider`, `MLXProvider` (interface only in v1).

```text
MODEL_PROVIDER=ollama
MODEL_BASE_URL=http://host.docker.internal:11434
MODEL_NAME=qwen3:30b-a3b   # or current equivalent; pin in .env
MODEL_CONTEXT_TOKENS=32768
```

## 14.1 Memory budget (architectural constraint)

64 GB total. Set and document:

```text
Local model weights + KV cache      ~20–24 GB   (30B-A3B q4 + 32k ctx)
macOS + apps                         ~8 GB
Docker Desktop VM (cap in settings)  16 GB
  postgres                           ≤2 GB
  temporal + ui                      ≤2 GB
  centrifugo                         ≤256 MB
  backend + worker (incl. Chromium)  ≤4 GB
  sandboxd                           ≤256 MB
  sandboxes                          ≤4 GB each, max 2 concurrent
```

Set `mem_limit` on every Compose service. Set Docker Desktop's VM memory to 16 GB. If the model is swapping, nothing else matters.

---

# 15. Memory and Context

Two scopes, both in Postgres, both visible and editable in the UI. No vector DB in v1.

**Profile memory** — long-lived user-level facts: preferences, constraints, devices, standing choices.

**Topic memory** — one structured document per topic:

```text
summary, objective, decisions, sources, successful_commands,
failed_approaches, important_artifacts, unfinished_work, next_actions
```

Context construction:

- Coordinator: current message, last N turns (token-budgeted), relevant profile memory, active topic summaries, pending approvals, recent important outputs.
- Topic worker: objective, profile subset, topic memory, relevant artifacts, last K worker events.

Compaction: when a conversation exceeds the budget, summarize older turns into a `conversation_summaries` row and drop them from context. Never replay whole histories into the local model.

Memory never contains secrets or AUTHENTICATED-classified content verbatim.

---

# 16. Realtime

Centrifugo is ephemeral fanout. Correctness never depends on delivery. Messages ≤ 16 KB.

Channels: `user:{id}`, `conversation:{id}`, `run:{id}`, `topic:{id}`, `browser:{session_id}`

Events:

```text
agent.started  agent.token  agent.message
tool.proposed  tool.started  tool.completed  tool.failed
topic.started  topic.progress  topic.completed  topic.failed
approval.required  approval.resolved
goal.triggered  goal.completed
browser.frame(metadata only)  browser.mode  browser.url_changed
notification.created
```

Every event carries a monotonically increasing `seq` per channel so clients can detect gaps and re-fetch.

Reconnect: `GET` authoritative state from FastAPI → render → subscribe → apply events with `seq` > last seen. Duplicate events are idempotent on the client.

---

# 17. Notifications and Telegram

Attention-demanding events go through NotificationService, separate from high-volume realtime: approval required, goal completed, important finding, agent failure, human action required.

Telegram, v1:

- long polling via `getUpdates` from the backend; outbound only
- allowed `chat_id` list from `.env`; anything else ignored and audited
- inline buttons `[Approve] [Deny]` carrying `approval_id`
- callback validation: chat_id allowed → approval exists → still PENDING → record decision → Temporal Update
- duplicate callbacks are no-ops
- optional lightweight commands: `/status`, `/topics`, `/cancel <topic>`

Telegram owns no state. No webhook, no public URL.

---

# 18. Phone Access

Tailscale only. Frontend is a PWA (manifest, service worker for shell caching, no offline data). Mobile-first views: chat, approvals, topics, goals, activity, browser viewer (read-only + takeover toggle). Native iOS is out of scope.

Auth: single owner user; session cookie issued by FastAPI after a local password login; Tailscale is the network perimeter, not the auth.

---

# 19. Database Schema (initial)

```text
users
conversations
messages                   (conversation_id, role, content, seq, created_at)
conversation_summaries
topics                     (conversation_id, objective, status, workflow_id, sandbox_id?, browser_session_id?)
topic_memory               (topic_id, jsonb document, version)
profile_memory             (user_id, key, value, updated_at)
goals                      (schedule/timer spec, workflow_id, status)
actions                    (action_id, approval_key, proposal jsonb, decision, executed_at, result jsonb)
approvals                  (approval_id, action_id, approval_key, status, summary, decided_by, channel, expires_at)
artifacts                  (id, topic_id, kind, path/volume ref, classification)
audit_events               (actor, event_type, ref ids, payload jsonb, created_at)
browser_sessions           (id, context, mode, current_url, status)
sandboxes                  (id, topic_id, container_id?, volume_name, status)
connector_accounts         (credential_ref, provider, encrypted blob)   # schema only in v1
notification_preferences
domain_allowlist           (domain, context, added_by, created_at)
```

Alembic migrations from day one. Do not mirror Temporal history into Postgres.

---

# 20. Observability

Structured JSON logs with `workflow_id, run_id, conversation_id, topic_id, action_id, approval_key, sandbox_id, browser_session_id`. Temporal UI exposed on localhost. OpenTelemetry only where cheap (FastAPI + Temporal interceptors). Do not overbuild.

Audit: every ActionProposal, decision, approval, execution result, and Telegram inbound is an `audit_events` row.

---

# 21. Explicitly Excluded From V1

OpenComputer · Kubernetes · Redis · dedicated egress proxy · standalone Sentinel/policy service · standalone browser service · vector database · recursive subagents · native iOS app · multi-model router · multi-user tenancy · distributed clusters · Telegram webhooks · external connectors (Gmail etc. — schema and credential_ref plumbing only, no live integrations).

Keep interfaces clean so these can be added if justified.

---

# 22. Docker Compose

Persistent services:

```text
web          (static PWA)
backend      (FastAPI + Telegram poller)
worker       (Temporal worker, PydanticAI, Playwright)
worker-model (Temporal worker serving only the model-inference queue, max_concurrent=1)
sandboxd     (Docker socket; network: sandbox-control + default for pulls only)
postgres
temporal
temporal-ui
centrifugo
```

Networks: `default` (all except sandboxes), `sandbox-control` (worker + sandboxd only). Sandboxes: `network_mode: none`.

Every service has `mem_limit`. `worker-model` may be the same image as `worker` with a different entrypoint flag.

---

# 23. Development Phases

Each phase ends with its acceptance test passing and `docs/progress.md` updated. Do not skip acceptance. Do not start phase N+1 until N passes. Do not add infrastructure "for later."

## Phase 0 — Design docs

Create: `docs/architecture.md`, `docs/threat-model.md`, `docs/temporal-design.md`, `docs/realtime-design.md`, `docs/sandbox-design.md`, `docs/model-provider.md`, `docs/policy-design.md`, `docs/progress.md`.

Define: module boundaries, workflows, activities, task queues, schema, Centrifugo channels/events, ToolIntent/ToolSpec/ActionProposal schemas, policy rule table, approval_key spec, sandboxd API, sandbox constraints, provider interface, memory budget.

## Phase 1 — Platform skeleton

Compose with all persistent services (sandboxd included, as a stub that only answers health). Vite PWA shell. FastAPI health. Alembic baseline migration. Centrifugo configured with JWT auth from backend.

Acceptance: `docker compose up --build` starts everything; the UI shows backend / Postgres / Temporal / Centrifugo / sandboxd / local model as online/offline; memory limits are set on every service.

## Phase 2 — Local model + policy skeleton + simple chat

OllamaProvider, model health endpoint, `ToolIntent`, `ToolRegistry`, `PolicyEngine` (returns ALLOW for all), `ToolGateway`, one trivial tool (`clock.now`), basic PydanticAI agent, non-durable chat endpoint (HTTP only, no Temporal yet).

Acceptance: user sends a message; local model responds; model calls `clock.now` and the call appears in `actions` + `audit_events` with decision ALLOW. No cloud API used. No tool path exists that bypasses the gateway (test asserts it).

## Phase 3 — Durable conversation

ConversationWorkflow, `send_message` Update, TemporalAgent, `call_model` on dedicated queue with concurrency 1, message persistence, Centrifugo token streaming, reconnect state reload.

Acceptance: kill the worker mid-response; restart; workflow completes correctly and the UI reconstructs state. Kill Centrifugo mid-stream; Postgres and Temporal remain correct.

## Phase 4 — Topics

`start_topic`, TopicWorkflow child, topic metadata, topic memory, max 3 concurrent topics, step limit, results returned to coordinator, cancellation with cleanup.

Acceptance: coordinator starts 3 independent topics; each survives a worker restart; cancelling one cleans up and leaves the others running.

## Phase 5 — sandboxd + sandbox

sandboxd full API, sandbox image, constraints enforced in sandboxd, durable workspace volumes, `sandbox.*` tools via gateway, trusted stager (artifact copy-in).

Acceptance (all automated): from inside a sandbox, cannot read host files, no Docker socket, no network (DNS and TCP fail), no env secrets, rootfs read-only, `/workspace` persists across container recreation, PID/mem limits enforced. Worker container has no Docker socket (test greps its mounts).

## Phase 6 — Policy rules + approvals table

Full rule table from Section 7, risk/side-effect classification in the registry, `approval_key`, `approvals` table, approval UI (web), Temporal durable wait, approval Update, expiry.

Acceptance: READ_ONLY actions execute; an EXTERNAL_WRITE stub tool blocks pending approval; workflow waits; restart all services; approve; workflow resumes without redoing prior work; approving with changed args is rejected; a forged request for another approval_id is rejected; double-approve is a no-op.

## Phase 7 — Browser

Playwright/Chromium in worker, research context, all `browser.*` tools, accessibility snapshot, screenshot artifacts, frame metadata via Centrifugo + frame endpoint, human takeover, domain allowlist, click/fill classification.

Acceptance: agent completes a simple public research task; no arbitrary JS tool exists (test); a click on a non-allowlisted domain requires approval; takeover pauses the agent and it resumes after.

## Phase 8 — Authenticated browser context

Persistent profile volume, `open_session(authenticated)` approval, AUTHENTICATED tagging, stricter mutation policy, heuristic escalation.

Acceptance: profile is not reachable from sandbox or workspace; a fill+click on an authenticated page requires approval; snapshot output is tagged and cannot be written to a sandbox without approval.

## Phase 9 — Goals / scheduling

GoalWorkflow, timers, Schedules, meaningful-result predicate, notification on flip.

Acceptance: "Check again tomorrow" wakes at the right time after a full service restart; a recurring goal fires on schedule and notifies only when the result changes.

## Phase 10 — Telegram

Long-polling poller, allowed chat_ids, approval buttons, callback validation, `/status`, `/cancel`.

Acceptance: pending approval sends a Telegram message; approving from Telegram resumes the workflow; a message from an unknown chat_id is ignored and audited; duplicate callback is harmless; no inbound port is opened (test: no published port on backend beyond the UI port).

## Phase 11 — PWA / phone polish

Manifest, service worker, responsive views, mobile approvals, browser viewer on phone, Tailscale documentation.

Acceptance: iPhone over Tailscale can chat, approve, view topics/goals/activity, and view the browser.

---

# 24. Test Requirements

**Boundary tests (must exist from Phase 2 and never be deleted):**

- no code path invokes an executor without passing through `ToolGateway` (static check: executors are private to the registry module)
- model output cannot set risk/side_effect/permissions (schema test)
- worker and backend containers have no Docker socket and no host home mounts (Compose introspection test)

**Temporal:** worker crash recovery, API restart, retry after transient model failure, approval wait across restart, timer survival, cancellation with cleanup, child recovery, Continue-As-New, model queue concurrency = 1.

**Sandbox:** all Phase 5 acceptance items, plus sandboxd rejects any create request that attempts to override constraints.

**Policy/approvals:** ALLOW executes; DENY never executes and is audited; REQUIRE_APPROVAL waits; approval bound to approval_key; changed args invalidate; forged approval rejected; duplicate decision no-op; expiry.

**Browser:** no `page.evaluate`/CDP surface; stale element id errors; takeover pauses/resumes; research context has no cookies; authenticated outputs tagged.

**Realtime:** Centrifugo outage does not corrupt state; reconnect reconstructs from API; duplicate and out-of-order events are handled via `seq`.

**Telegram:** unknown chat_id ignored; valid callback resumes the right action; invalid approval_id rejected; duplicate callback harmless.

**Model:** structured tool calling; multi-step loop; topic delegation; malformed output repair then fail.

---

# 25. Anti-Patterns (hard rules)

```text
use OpenComputer
mount the Docker socket anywhere except sandboxd
let the model set risk / side_effect / permissions / classification
add a tool that does not go through ToolGateway
execute model-generated shell on macOS
put credentials or browser profiles in a sandbox
put secrets in prompts, memory, logs, or Centrifugo
key approvals on anything non-deterministic
use Centrifugo as a database or depend on delivery for correctness
store application data only in Temporal
reimplement workflow durability in Postgres
Python sleep loops for scheduling
mount ~ or any host path in a sandbox
expose page.evaluate / CDP / raw Playwright
recursive or depth>1 subagents
Telegram webhooks / public ingress / port forwarding
add Redis, Kubernetes, a vector DB, or a second orchestrator
```

---

# 26. Repository Layout

```text
local-muse/
  apps/web/                      Vite React PWA
  backend/
    app/
      api/                       FastAPI routers (chat, approvals, topics, goals, browser, memory, health)
      agents/                    coordinator, topic_worker, deps
      tools/                     registry, specs, gateway, executors/
      policy/                    engine, rules, classification
      workflows/                 conversation, topic, goal
      activities/
      browser/                   controller, snapshot, contexts, frames
      sandbox/                   sandboxd client
      memory/
      notifications/             service, telegram poller
      realtime/                  centrifugo publisher, seq
      models/                    providers
      db/                        models, alembic
      settings/
    tests/
  sandboxd/                      separate service, own Dockerfile
  sandbox/                       sandbox image Dockerfile + scripts
  infra/
    docker-compose.yml
    centrifugo/
    temporal/
  docs/
    architecture.md  threat-model.md  temporal-design.md  realtime-design.md
    sandbox-design.md  policy-design.md  model-provider.md  progress.md
  .env.example
  Makefile
  README.md
```

---

# 27. Development Workflow For Claude

For every phase:

1. inspect the current repository
2. update the relevant `docs/*.md` before major implementation
3. implement only the current phase
4. run unit + integration tests, including all boundary tests
5. fix failures
6. run lint (ruff) and type checks (mypy/pyright strict on `tools/`, `policy/`, `sandbox/`)
7. verify `docker compose up --build` if infrastructure changed
8. update `docs/progress.md`
9. summarize: what changed, what works, what remains, known limitations

Do not skip acceptance tests. Do not jump ahead unless required to unblock the current phase, and say so when you do. Do not add infrastructure because it may be useful later.

---

# 28. First Task For Claude

Complete **Phase 0 and Phase 1 only**.

Deliver:

```text
docs/architecture.md
docs/threat-model.md
docs/temporal-design.md
docs/realtime-design.md
docs/sandbox-design.md
docs/policy-design.md
docs/model-provider.md
docs/progress.md
infra/docker-compose.yml        (all persistent services incl. sandboxd stub, mem_limits, networks)
.env.example
backend skeleton with health endpoints
sandboxd skeleton with health endpoint (Docker socket mounted, no other API yet)
apps/web skeleton (Vite PWA) with a status page
Alembic baseline migration
Centrifugo config
Temporal config
Phase 1 integration tests
```

`docs/temporal-design.md` must explicitly cover: workflow ids, ConversationWorkflow, TopicWorkflow, GoalWorkflow, child relationships, Signals vs Updates, activity boundaries, task queues and the model-inference concurrency=1 queue, retry behavior, idempotency, cancellation and cleanup, approval waits, Continue-As-New, TemporalAgent responsibilities, what stays in Temporal vs Postgres.

`docs/policy-design.md` must explicitly cover: ToolIntent vs ActionProposal, that classification is registry-owned, the rule table, browser context rules, `approval_key` composition and what is excluded from it.

`docs/sandbox-design.md` must explicitly state: only sandboxd holds the Docker socket; sandbox has no network, no credentials, no Docker socket, no host mounts; only `/workspace` is writable; constraints are enforced by sandboxd and cannot be overridden by callers.

`docs/realtime-design.md` must explicitly state: Centrifugo is ephemeral fanout, not storage; no invariant depends on message history; `seq`-based gap detection; frames are metadata only.

Do not implement OpenComputer, Redis, Kubernetes, native mobile, Telegram webhooks, or external connectors.

Complete Phase 1 and prove it works before moving forward.

---

# 29. Definition of Success

```text
User on phone: "Research X and keep checking until you find Y."

Local Muse:
- creates a durable workflow
- delegates a topic
- researches with the browser (research context)
- analyzes in a no-network sandbox created by sandboxd
- persists memory
- keeps running after the UI disconnects
- sleeps/wakes through Temporal
- sends a Telegram alert when something matters
- asks approval, bound to the exact action, before any external side effect
- resumes after approval
- survives process/container/laptop restarts
- runs the model locally on the Mac
```

It should feel like a persistent personal computer agent, not a chatbot with tools.

Priority order when trade-offs arise:

```text
1. privilege separation and sandboxing
2. policy-gated side effects with content-bound approvals
3. durability
4. local execution
5. persistent memory
6. background operation
7. mobile reachability
8. realtime visibility
```

Everything else is secondary.
