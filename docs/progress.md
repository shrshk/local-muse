# Progress

Spec: `plans/local_muse_claude_handoff_v2.md`.

| Phase | Status |
|---|---|
| 0 Design docs | done |
| 1 Platform skeleton | done |
| 2 Local model + policy skeleton + chat | done |
| 3 Durable conversation | not started |
| 4 Topics | not started |
| 5 sandboxd + sandbox | not started |
| 6 Policy rules + approvals | not started |
| 7 Browser | not started |
| 8 Authenticated browser | not started |
| 9 Goals | not started |
| 10 Telegram | not started |
| 11 PWA / phone | not started |

## Phase 0 — Design docs

Done 2026-09-26. Docs: architecture, threat-model, temporal-design, realtime-design,
sandbox-design, policy-design, model-provider.

Decisions beyond the spec:

- Code layout follows the handler/controller/schema module pattern (`architecture.md` → Code
  layout). Spec §26 subsystem dirs keep their names.
- SQLAlchemy Core tables in `shared/tables.py`, updated with every migration.
- Tables land per phase, not all in the baseline (`architecture.md` → Schema rollout).
- `service_heartbeats` table carries worker liveness and sandboxd reachability to the backend.
- sandboxd is on `sandbox-control` only; no default network (pulls go through the daemon).
- Auth (owner login) planned for Phase 2; the spec names no phase for it.

## Phase 1 — Platform skeleton

Done 2026-09-26.

What works:

- `make env && make up-detached` builds and starts all 10 services (incl. one-shot `migrate`);
  all report healthy on a cold start.
- `GET /api/health` aggregates backend, postgres, temporal, centrifugo, model (direct probes)
  and worker, worker-model, sandboxd (heartbeat rows written by the workers).
- Web status page (Vite + React + TS PWA behind nginx) renders every component and its own
  Centrifugo connection, authenticated with a backend-minted HS256 JWT.
- Stopping sandboxd flips it to offline within ~6 s; restart recovers within ~12 s.
- Alembic baseline `0001` (`service_heartbeats`); `tables.py` mirrors it.

Tests:

- `make check`: ruff, ruff format, mypy strict (backend + sandboxd), tsc, 30 unit/boundary tests.
- Boundary (static compose): only sandboxd mounts the Docker socket; no host-home mounts; every
  service has `mem_limit`; `sandbox-control` is internal with only worker + sandboxd; sandboxd
  hardened; published ports bind 127.0.0.1.
- `make test-integration` (10, live stack): all core components online; Centrifugo accepts a
  backend token and rejects a forged one (3500); only sandboxd's container has the socket;
  every container has a memory limit; backend cannot resolve sandboxd; worker gets 401 without
  the token and 200 with it; sandboxd has no egress; migrations at head.

Known limitations:

- Model tile needs Ollama running on the host with `MODEL_NAME` pulled.
- No auth yet; realtime token endpoint is open on loopback (see architecture.md → Auth).
- Workers register only a `ping` activity; no workflows until Phase 3.
- Starlette warns that its TestClient's httpx backend is deprecated (sandboxd tests); harmless.

## Phase 2 — Local model, policy skeleton, chat

Done 2026-09-26.

What works:

- Owner login (argon2, signed `HttpOnly` cookie); `make create-user`. All non-health endpoints
  require it; conversations are private to their owner.
- `ToolIntent → ToolRegistry → ActionProposal → PolicyEngine (ALLOW all) → ToolGateway →
  executor`, with `actions` and `audit_events` rows for every step. One tool: `clock.now`.
- PydanticAI coordinator on `qwen3.8:27b` via Ollama (`/v1`). Tools reach the model as a
  `FunctionToolset` generated from the registry; each only forwards to the gateway. One repair
  attempt on bad args; max 8 model requests per turn.
- Non-durable chat API + web chat (conversation list, timeline of messages and tool-call chips).
- `GET /api/models/health`.

Acceptance evidence (live, 2026-09-26):

- "What is the current time in Asia/Tokyo? Use the clock tool." → model called `clock.now`
  `{"timezone": "Asia/Tokyo"}`; `actions`: READ_ONLY / ALLOW / executed; `audit_events`:
  `action.proposed, action.decided, action.executed`; reply quoted the tool's time.
- Browser: "Tokyo and New York" → two parallel `clock.now` calls, both ALLOW, correct answer.
- No cloud API: offline mode, provider `ollama` at `host.docker.internal:11434`, no cloud keys
  in the backend env (integration test).
- No gateway bypass: AST boundary tests (only `specs.py` imports executors; only `gateway.py`
  reads `.executor`; agents never call `propose`/`evaluate`), plus a fake-model test where a
  model-supplied `risk` arg is rejected and nothing executes.

Tests: `make check` 59 unit/boundary; `make test-integration` 15 (incl. the real-model turn).

Known limitations:

- Assistant markdown renders as plain text (Phase 11 polish).
- Chat history sent to the model is the last 20 messages; token-budgeted context and compaction
  come with memory (Phase 4).
- A model failure leaves the user message saved without a reply (returns 502).
- Test users `itest-*` and `e2e-ui` accumulate in the local DB; harmless, delete at will.

## Decisions log

- 2026-09-26: `ModelProvider` returns a PydanticAI `Model` instead of re-declaring
  `complete`/`stream` (docs/model-provider.md).
- 2026-09-26: Removed an `env-sync` make target; permission rules block testing anything that
  writes `.env`, so new keys are added by hand (compose names the missing key).
- 2026-09-26: Docker Desktop VM stays at 32 GB. It is a ceiling, not a reservation; revisit only on
  memory pressure with the model loaded (measure in Phase 2).
