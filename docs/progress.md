# Progress

Spec: `plans/local_muse_claude_handoff_v2.md`.

| Phase | Status |
|---|---|
| 0 Design docs | done |
| 1 Platform skeleton | in progress |
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

## Open questions

- Docker Desktop VM is 32 GB on this Mac; budget assumes 16 GB. Leave or lower?
