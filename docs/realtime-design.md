# Realtime design

**Centrifugo is ephemeral fanout, not storage.** No invariant depends on message history or
delivery. If Centrifugo is down, Postgres and Temporal stay correct and clients recover by
reloading from the API.

## Auth

- Connection token: HS256 JWT minted by the backend (`POST /api/realtime/token`), `sub` = user
  id, short TTL. Centrifugo verifies it with `CENTRIFUGO_CLIENT_TOKEN_HMAC_SECRET_KEY`.
- Server publishes through the HTTP API with `CENTRIFUGO_HTTP_API_KEY`. Clients never publish.
- Private channels (`user:`, `conversation:`, …) require a subscription token minted by the
  backend after it checks ownership. Added with the first channel in Phase 3.
- The browser reaches Centrifugo through nginx at `/connection/websocket` (same origin).

## Channels

```text
user:{id}  conversation:{id}  run:{id}  topic:{id}  browser:{session_id}
```

Each prefix is a Centrifugo namespace. No history, no recovery, no presence: correctness does
not use them.

## Events

```text
agent.started  agent.token  agent.message
tool.proposed  tool.started  tool.completed  tool.failed
topic.started  topic.progress  topic.completed  topic.failed
approval.required  approval.resolved
goal.triggered  goal.completed
browser.frame  browser.mode  browser.url_changed
notification.created
```

Envelope:

```json
{ "type": "tool.completed", "seq": 118, "ts": "…", "data": { "action_id": "…" } }
```

Max 16 KB per message. Large payloads are referenced by id and fetched from the API.

## Ordering and gaps

- `seq` increases monotonically per channel. The publisher allocates it from Postgres
  (a per-channel counter row), not in process memory, so a restart cannot reuse numbers.
- Client keeps `last_seq` per channel. `seq <= last_seq` → drop (duplicate). `seq > last_seq + 1`
  → gap → re-fetch authoritative state from the API.

## Reconnect

1. `GET` authoritative state from FastAPI.
2. Render.
3. Subscribe.
4. Apply events with `seq` > the state's `seq`.

## Browser frames

Frames are **metadata only** over Centrifugo:

```json
{ "type": "browser.frame", "session_id": "b17", "frame_version": 412 }
```

The client fetches `GET /api/browser/{session_id}/frame?v=412` (JPEG). ~2 fps cap.
