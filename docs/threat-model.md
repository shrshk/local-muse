# Threat model

## Trust zones

```text
UNTRUSTED
  model output (all of it: tool calls, "reasoning", structured output)
  web page content
  sandbox contents and sandbox output
  Telegram inbound messages
  files downloaded by the browser

TRUSTED (code we wrote)
  backend, worker, worker-model, sandboxd

PRIVILEGED
  sandboxd                     Docker socket
  credential store             backend only
  authenticated browser profile worker only, never a sandbox
```

## Threats and mitigations

| # | Threat | Mitigation | Test phase |
|---|---|---|---|
| 1 | Prompt injection via a web page makes the model emit a harmful `ToolIntent` | Registry owns classification; policy + content-bound approvals; browser click/fill/press are never READ_ONLY | 6, 7 |
| 2 | Compromised worker → host compromise | Worker has no Docker socket, no host mounts, no credentials beyond executors' needs | 1 (compose test), 5 |
| 3 | Sandbox escape | cap_drop ALL, non-root uid 10001, no-new-privileges, network none, pids/cpu/mem limits, read-only rootfs, only `/workspace` writable | 5 |
| 4 | Approval replay / substitution | Approval bound to `approval_key` = sha256 of canonical action contents | 6 |
| 5 | Forged approval request | Session auth on FastAPI; Telegram callbacks checked against allowed `chat_id` and a PENDING approval | 6, 10 |
| 6 | Credential leak into prompts, memory, sandbox, logs, Centrifugo | `credential_ref` only; resolved in the executor at run time; AUTHENTICATED tagging on logged-in browser output | 8 |
| 7 | Runaway recursion / cost | No recursive agents; topic depth 1; max 3 topics per conversation; step limit per run; model queue concurrency 1 | 4 |
| 8 | sandboxd API reached by something other than worker | Internal `sandbox-control` network (worker + sandboxd only) plus a bearer token from `.env` | 1 |
| 9 | LAN or internet exposure | All published ports bind `127.0.0.1`; phone access only via Tailscale; no inbound Telegram webhook | 1, 10, 11 |

## Residual risks (accepted for v1)

- sandboxd runs as root inside its container to use the socket. It has `cap_drop: ALL`,
  `no-new-privileges`, a read-only rootfs and no egress. A sandboxd compromise is still a host
  (Docker VM) compromise; keeping its API narrow is the control.
- One Postgres superuser serves both the app and Temporal. Postgres is inside the trusted zone.
- Credential encryption key lives in `.env`.
- Browser escalation heuristics (Phase 8) are pattern-based and incomplete by design.
- Before auth lands (Phase 2), anyone who can reach `127.0.0.1:8080` can read health and get a
  Centrifugo connection token. Channels are not subscribable without later subscription rules.
