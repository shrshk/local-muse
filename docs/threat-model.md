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
| 6 | Credential leak into prompts, memory, sandbox, logs, Centrifugo | `credential_ref` only; the logged-in browser profile lives on a worker-only volume (never mounted elsewhere, tested from inside a sandbox); AUTHENTICATED tagging and conversation taint gate sandbox and memory writes; text typed during takeover goes through a short-lived inbox row, not Temporal history (tested) | 8 |
| 7 | Runaway recursion / cost | No recursive agents; topic depth 1; max 3 topics per conversation; step limit per run; model queue concurrency 1 | 4 |
| 8 | sandboxd API reached by something other than worker | Internal `sandbox-control` network (worker + sandboxd only) plus a bearer token from `.env` | 1 |
| 9 | LAN or internet exposure | All published ports bind `127.0.0.1`; phone access only via Tailscale; no inbound Telegram webhook | 1, 10, 11 |
| 10 | Prompt-injected page steers the browser to internal services (Temporal UI can terminate workflows; Ollama; sandboxd; cloud metadata) | Every browser request's host must resolve only to globally routable addresses (`browser/netguard.py`, Playwright route guard); only http/https URLs; tested against temporal-ui, host.docker.internal, sandboxd, loopback, 169.254.169.254, file:// | 7 |

## Residual risks (accepted for v1)

- sandboxd runs as root inside its container to use the socket. It has `cap_drop: ALL`,
  `no-new-privileges`, a read-only rootfs and no egress. A sandboxd compromise is still a host
  (Docker VM) compromise; keeping its API narrow is the control.
- One Postgres superuser serves both the app and Temporal. Postgres is inside the trusted zone.
- Credential encryption key lives in `.env`.
- Browser escalation heuristics are pattern-based and incomplete by design.
- Browser network guard: DNS rebinding between the guard's lookup and Chromium's own lookup is
  not closed; WebSocket connections are not routed through the guard. Both are known gaps.
- Page content is untrusted input to the model (prompt injection). Mitigation is the policy
  boundary, not the model: clicks need approval off the allowlist, external writes need approval.
- Authenticated page content that the agent reads is in Temporal history (activity results) and
  in model context, like any tool output. Only human-typed text is kept out of history.
- Conversation summaries may paraphrase authenticated content; they are not verbatim copies.
- Telegram trusts the chat id Telegram reports; a stolen phone with the chat open can approve.
  Messages show only the action summary, never page content or secrets.
- Login has no rate limiting yet; the perimeter is loopback now and Tailscale in Phase 11.
