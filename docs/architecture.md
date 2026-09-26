# Architecture

Local Muse is a local-first personal agent on one Mac. The build spec is
`plans/local_muse_claude_handoff_v2.md`; this doc records how the code is shaped to meet it.

## Principles (short form)

1. Intelligence is not authority. The model emits `ToolIntent`; the trusted registry,
   policy engine and executors decide and act. See `policy-design.md`.
2. Every tool call goes through `ToolGateway` from the first tool onward.
3. Modular monolith. The only extra process for privilege reasons is `sandboxd`.
4. Durability: Temporal owns execution state, Postgres owns application state, Centrifugo
   owns nothing.

## Topology

```text
iPhone PWA / Mac browser ── Tailscale ──▶ web (nginx: static PWA, /api, /connection)
                                            │
                        ┌───────────────────┼──────────────────────────┐
                        ▼                   ▼                          │
                     backend ──────── centrifugo                       │
                  (FastAPI, Telegram)       ▲                          │
                        │                   │ publish                  │
                        ├── postgres ◀──────┤                          │
                        └── temporal ◀── worker ──(sandbox-control)──▶ sandboxd ──▶ docker.sock
                                            │                               │
                                       worker-model                 sandbox containers
                                   (model-inference queue,          (network none)
                                    max_concurrent=1)
                                            │
                                   Ollama (native macOS, host.docker.internal:11434)
```

## Services

| Service | Image | Role | Networks |
|---|---|---|---|
| web | `apps/web` (nginx) | Static PWA; reverse proxy for `/api` and `/connection` | default |
| backend | `backend` | HTTP API, auth, Temporal client, Centrifugo tokens, Telegram poller | default |
| worker | `backend` | Temporal worker: workflows, tools, policy, browser, sandbox client | default, sandbox-control |
| worker-model | `backend` | Temporal worker for `model-inference` only, concurrency 1 | default |
| sandboxd | `sandboxd` | Only holder of the Docker socket; narrow sandbox API | sandbox-control (internal) |
| postgres | postgres:16 | App DB `muse`; Temporal DBs `temporal`, `temporal_visibility` | default |
| temporal | auto-setup | Temporal server | default |
| temporal-ui | temporalio/ui | Operator UI on localhost | default |
| centrifugo | centrifugo v6 | Ephemeral fanout | default |
| migrate | `backend` | One-shot `alembic upgrade head` before backend/worker start | default |

`sandbox-control` is `internal: true`. sandboxd has no route out. Image pulls run in the
Docker daemon, not in sandboxd, so sandboxd does not need the default network. (The spec
allowed default "for pulls only"; it is not needed.)

## Code layout

```text
backend/src/muse/
  api/            FastAPI app, deps, routers/ (transport only: parse, call handler, shape)
  modules/        product domains: {domain}_controller.py (DB), _handler.py (logic), _schema.py
  worker/         Temporal worker entry point and process-level loops
  shared/         settings, logger, db engine, tables (SQLAlchemy Core)
  # later phases, per spec §26:
  agents/ tools/ policy/ workflows/ activities/ browser/ sandbox/ realtime/ models/
  notifications/ memory/
sandboxd/src/sandboxd/   separate package and image
apps/web/                Vite + React + TypeScript PWA
infra/                   compose, centrifugo, temporal, nginx config
```

Conventions:

- Routers hold no logic. Handlers are classes that own orchestration. Controllers are classes
  that take a connection and run SQLAlchemy Core queries only.
- Tables live in `shared/tables.py` as SQLAlchemy Core `Table` objects. Every Alembic migration
  that changes shape updates `tables.py` in the same commit.
- Logging: `from muse.shared.logger import get_logger`. Events are stable snake_case ids;
  values go in kwargs. `import logging` is banned by ruff `TID251`.
- No bare or blind `except`. Catch a specific type.

## Schema rollout

Tables from spec §19 land in the phase that first uses them, not all at once.

| Phase | Tables |
|---|---|
| 1 | `service_heartbeats` (worker liveness + sandboxd reachability; see below) |
| 2 | `users`, `conversations`, `messages`, `actions`, `audit_events` |
| 3 | `conversation_summaries` |
| 4 | `topics`, `topic_memory`, `profile_memory` |
| 5 | `sandboxes`, `artifacts` |
| 6 | `approvals`, `domain_allowlist` |
| 7–8 | `browser_sessions` |
| 9 | `goals`, `notification_preferences` |
| — | `connector_accounts` (schema only, when credential plumbing lands) |

### Why `service_heartbeats`

The backend cannot reach sandboxd (only worker shares `sandbox-control`), and workers expose no
HTTP port. Each worker upserts a heartbeat row every 10 s carrying its own liveness and, for
`worker`, the result of a sandboxd health call. The backend reads the rows; a row older than
30 s reads as offline. This keeps the network boundary intact without adding a port.

## Health model

`GET /api/health` returns one entry per component: `backend`, `postgres`, `temporal`,
`centrifugo`, `worker`, `worker-model`, `sandboxd`, `model`. Each probe is independent and
time-boxed (2 s). The web status page renders them and separately shows its own Centrifugo
connection state, which proves the JWT path end to end.

## Memory budget

Docker Desktop VM target: 16 GB (currently 32 GB on this Mac; either is fine, 16 is the budget).

| Service | mem_limit |
|---|---|
| postgres | 2g |
| temporal | 1536m |
| temporal-ui | 256m |
| centrifugo | 256m |
| backend | 1g |
| worker | 2560m (Chromium arrives in Phase 7) |
| worker-model | 512m |
| sandboxd | 256m |
| web | 64m |
| migrate | 256m (one-shot) |
| sandboxes | 4g each, max 2 concurrent |

Steady state without sandboxes ≈ 8.5 GB. Ollama runs natively and is outside the VM
(~20–24 GB for a 30B-A3B q4 model with 32k context).

## Auth

Spec §18: single owner, password login, session cookie. No phase in §23 names it, but approvals
(Phase 6) need it and conversations (Phase 3) should have it. Plan: land login in Phase 2 with
the first user-owned table. Until then every port binds to `127.0.0.1` and the only
unauthenticated write-free endpoints are health and the Centrifugo connection token.
