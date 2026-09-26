# local-muse

Local-first personal AI agent on one Mac: durable Temporal workflows, a local model via Ollama,
policy-gated tools, no-network Docker sandboxes, and a PWA reachable over Tailscale.

Build spec: `plans/local_muse_claude_handoff_v2.md`. Design docs: `docs/`. Status:
`docs/progress.md`.

## Quick start

Needs Docker Desktop, uv, and Node 22+.

```bash
make env           # .env with random secrets
make up-detached   # build + start, waits for health
open http://localhost:8080
```

Temporal UI: http://localhost:8233.

Local model (optional until Phase 2):

```bash
brew install ollama && ollama serve
ollama pull qwen3:30b-a3b
```

## Development

```bash
make check             # ruff, mypy strict, tsc, unit + boundary tests
make test-integration  # against the running stack
make web-dev           # Vite on :5173, proxied to the stack
make help              # everything else
```

## Layout

```text
backend/    FastAPI API + Temporal workers (package `muse`)
sandboxd/   sandbox controller, the only holder of the Docker socket
apps/web/   Vite + React + TypeScript PWA
infra/      docker-compose, Centrifugo and Temporal config
docs/       design docs and progress log
```
