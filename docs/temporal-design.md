# Temporal design

Namespace `default` (created by `auto-setup`). Server and visibility use Postgres databases
`temporal` and `temporal_visibility` in the shared instance.

## Workflow ids

| Workflow | id | Parent |
|---|---|---|
| ConversationWorkflow | `conv-<conversation_id>` | — |
| TopicWorkflow | `topic-<topic_id>` | ConversationWorkflow |
| GoalWorkflow | `goal-<goal_id>` | — (starts TopicWorkflows per fire) |

Ids are deterministic so a restart or retry finds the existing run instead of starting a second.

## ConversationWorkflow

- Receives user messages through the `send_message` **Update** (client gets accept/reject).
- Runs the coordinator agent. Starts TopicWorkflow children (max 3 concurrent); gets their
  `TopicResult` on child completion.
- Tracks pending approvals by `approval_id`.
- Continue-As-New after N agent runs or history > 10k events. Carries ids and a compact state
  struct only; message content stays in Postgres.

## TopicWorkflow

- Runs the topic worker agent loop with a step limit (default 60).
- Owns at most one sandbox and one browser session.
- Waits durably on approvals and on human browser takeover.
- Returns `TopicResult` to the parent. Continue-As-New when step history grows large.

## GoalWorkflow

- One-shot delay: `workflow.sleep` (a durable Temporal timer).
- Recurring: a Temporal Schedule that starts a TopicWorkflow per fire.
- "Notify when X": recurring topic with a `meaningful_result` predicate; notify only on a flip.
- No Python sleep loops for scheduling.

## Signals vs Updates

| Use | Mechanism |
|---|---|
| User message, approval decision, takeover on/off, cancel-with-ack | Update (synchronous accept/reject, validator rejects bad input before history) |
| Topic progress hints to parent, other fire-and-forget workflow-to-workflow notes | Signal |

## Activities

```text
call_model                 model-inference queue
persist_message
persist_topic_memory
persist_action
publish_realtime_event
send_notification
browser_*                  one per browser tool
sandbox_*                  one per sandboxd call
execute_external_action    approved side effects, idempotent on action_id
```

Each activity is one retry boundary. Do not split further.

## Task queues

| Queue | Worker service | Concurrency |
|---|---|---|
| `muse-main` | worker | default |
| `model-inference` | worker-model | `max_concurrent_activities=1` |

One local model means one inference at a time. The queue does the serializing; there is no
scheduler. Browser I/O, sandbox compute and timers on `muse-main` still overlap.

`call_model`: heartbeat every 10 s, start-to-close 10 min, heartbeat timeout 30 s.

## Retry and idempotency

- Safe to retry: `call_model`, `http.get`, `browser.navigate`, `browser.snapshot`, sandbox reads,
  all `persist_*` (upserts keyed by ids).
- Never blind-retry side effects in {MESSAGE_SEND, REMOTE_UPDATE, PURCHASE, DELETE}.
  `execute_external_action` retries only when the executor is registered `idempotent=True`, and
  it passes `action_id` as the idempotency key.
- A retry after a transient failure reuses the same `action_id` and `approval_key`, so it does
  not re-prompt the human.

## Approval waits

1. Policy returns REQUIRE_APPROVAL → `persist_action` + approvals row (PENDING).
2. Workflow records `approval_id` in state and waits: `workflow.wait_condition(lambda: decided)`.
3. `decide_approval` Update (from FastAPI or the Telegram poller) validates the id is pending in
   workflow state, sets the decision, returns ack.
4. Expiry: the wait has a 7-day timeout → DENIED(expired).

The wait is Temporal state, so it survives API, worker and laptop restarts.

## Cancellation and cleanup

Cancel propagates as Temporal cancellation (conversation → topics). TopicWorkflow's `finally`
runs `sandbox_destroy` and `browser_close_session` in a shielded (non-cancellable) scope so
cleanup always happens. Workspace volumes are kept.

## TemporalAgent

PydanticAI's `TemporalAgent` wraps the agent so each model request and tool call runs as an
activity. Responsibilities:

- model requests route to `call_model` on `model-inference`;
- tool calls route through `ToolGateway` inside activities, never in workflow code;
- the agent loop state is replayable from history; no non-deterministic calls in workflow code.

## Temporal vs Postgres

```text
Temporal   workflow state, timers, waits, child relationships, retries
Postgres   anything a user sees or edits, and everything the audit needs
Memory     nothing that must survive a restart
```

Temporal history is not mirrored into Postgres. Postgres state is not used to reimplement
workflow durability.

## Implementation (Phase 3)

- **TemporalDurability, not TemporalAgent.** PydanticAI 2.x deprecates `TemporalAgent`; the
  coordinator is a plain `Agent` with the `TemporalDurability` capability
  (`agents/coordinator.py`). Outside a workflow it is transparent, so unit tests run the same agent.
- **Activity names** are persisted compatibility data: `agent__coordinator__model_request_stream`,
  `agent__coordinator__toolset__gateway__...`, `conversation.persist_message|load_turn|publish_event`.
  Do not rename the agent (`coordinator`) or toolset (`gateway`) without draining workflows.
- **Worker split.** `worker` (queue `muse-main`) runs `ConversationWorkflow`, conversation
  activities, and tool / tool-event activities; `PydanticAIPlugin` registers the agent's activities
  from the workflow's `__pydantic_ai_agents__`. `worker-model` registers only activities whose name
  contains `__model_` and runs at `max_concurrent_activities=1` on `model-inference`.
- **Model activity config:** start-to-close 10 min, heartbeat timeout 30 s, 3 attempts. PydanticAI
  does not heartbeat, so `worker/interceptors.py` heartbeats every 10 s for any running activity.
  A killed worker's model call is retried ~30 s later (tested).
- **Deps** are ids only (`AgentDeps`), so they serialize into activities. The gateway is built inside
  the tool activity from a per-process `AgentRuntime` configured at worker start.
- **Tool retries** follow the tool spec: `idempotent` tools use `ToolSpec.retry.max_attempts`, all
  others run once (per-tool `metadata={"temporal": ActivityConfig(...)}`). A retried read-only
  call records a new proposal; `action_id` reuse across retries arrives with approvals (Phase 6).
- **Start and send.** The API calls `execute_update_with_start_workflow` with
  `id_conflict_policy=USE_EXISTING`, by type name (the API never imports workflow code). The
  `send_message` Update persists the user message (id from `workflow.uuid4()`, insert is
  idempotent) and returns `{message_id, seq, turn_id}`. Validator rejects >5 pending messages.
- **Turn loop.** One turn at a time. `load_turn` reads the prompt and the last N messages from
  Postgres; the agent runs; `persist_message` stores the reply. A failed run (`AgentRunError` or
  `ActivityError` after retries) publishes `agent.failed` and records `last_error`; the workflow
  keeps going.
- **Lifetime.** After 24 h idle the run completes; the next message starts a new run via
  update-with-start. Continue-As-New after 50 turns (or when Temporal suggests it), carrying only
  `ConversationState` (ids, limits, pending turn ids). Waits for `all_handlers_finished` first.
- **Status query** `status` → running turn, pending turns, last error. The API uses it in `/state`.
- **Payloads** use PydanticAI's payload converter (`PydanticAIPlugin`) on every client and worker.
- **Sandbox.** Workflow imports go through `imports_passed_through()`; the agent is built at import
  (`agents/instances.py`) because workflows reference it at class definition.

## Implementation (Phase 4): topics

- **Starting.** The coordinator calls the `topic.start` tool (through the gateway like any tool).
  The executor checks depth (no `topic_id` in context), trigger (`user` only, so relaying a topic
  result can never re-start work) and the limit (3 active per conversation, counted under the
  conversation row lock), then writes a `pending` topic and its memory. It starts nothing.
- **Children.** After a coordinator turn, the conversation workflow calls `topic.claim_pending`
  (pending → running, idempotent) and starts `TopicWorkflow` children, id `topic-<id>`,
  `parent_close_policy=REQUEST_CANCEL` so cleanup always runs.
- **TopicWorkflow** runs the `topic_worker` agent (output `TopicReport`, request limit 60, gateway
  toolset without `topic.start`), then `topic.finish` records status, result and merges the report
  into topic memory (optimistic, retried against concurrent user edits). Tokens stream to
  `topic:<id>`; lifecycle events (`topic.started|completed|failed|cancelled`) go to the
  conversation channel.
- **Cancellation.** `POST /api/topics/{id}/cancel`: pending topics are marked cancelled in place;
  running ones get Temporal cancellation. The workflow catches `CancelledError`, records
  `cancelled` (memory notes it), publishes, and re-raises, so Temporal shows CANCELED.
- **Results.** A watcher task per child awaits its handle, persists an `event` message
  ("Topic X completed/failed/was cancelled"), publishes `event.message`, and for completions queues
  a `topic_result` turn. That turn's prompt is the event (`[event] …`), so the coordinator relays it.
- **Guards.** The conversation workflow does not idle-complete or Continue-As-New while topics are
  active (children belong to the run).

## Implementation (Phase 6): approval waits

- Both ConversationWorkflow and TopicWorkflow run agents through `run_with_approvals`, own an
  `ApprovalGate`, and expose `decide_approval` (Update + validator). Status queries report
  `waiting_approval_ids`.
- The wait is `workflow.wait_condition(gate.all_decided, timeout=approval_timeout_s)`; the timer
  and the pending set are Temporal state, so a restart of every service (tested) resumes the same
  wait. Model and tool activities that completed before the wait are not re-run on resume.
- `ConversationState.approval_timeout_s` / `TopicInput.approval_timeout_s` (default 7 days) set
  both the timer and the approval's `expires_at`.
- Agents' output type includes `DeferredToolRequests`, so a paused run is a normal result.
