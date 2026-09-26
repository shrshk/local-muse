# Progress

Spec: `plans/local_muse_claude_handoff_v2.md`.

| Phase | Status |
|---|---|
| 0 Design docs | done |
| 1 Platform skeleton | done |
| 2 Local model + policy skeleton + chat | not started |
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

## Decisions log

- 2026-09-26: Docker Desktop VM stays at 32 GB. It is a ceiling, not a reservation; revisit only on
  memory pressure with the model loaded (measure in Phase 2).
