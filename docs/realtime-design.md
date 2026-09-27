# Realtime design

**Centrifugo is ephemeral fanout, not storage.** No invariant depends on message history or
delivery. If Centrifugo is down, Postgres and Temporal stay correct and clients recover by
reloading from the API.

## Auth

- Connection token: HS256 JWT minted by the backend (`POST /api/realtime/token`), `sub` = user
  id, short TTL. Centrifugo verifies it with `CENTRIFUGO_CLIENT_TOKEN_HMAC_SECRET_KEY`.
- Server publishes through the HTTP API with `CENTRIFUGO_HTTP_API_KEY`. Clients never publish.
- Private channels (`user:`, `conversation:`, …) require a subscription token minted by the
  backend after it checks ownership: `POST /api/realtime/subscribe_token {conversation_id}`.
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

## Implementation (Phase 3)

- `realtime/publisher.py`: allocates `seq` from `realtime_channel_seqs` (upsert + 1), then POSTs
  to Centrifugo's `/api/publish`. A Centrifugo failure is logged (`realtime_publish_failed`) and
  swallowed; the seq is still consumed, so clients see a gap and refetch.
- Published today on `conversation:{id}`: `agent.started`, `agent.token` (batched ~48 chars or
  150 ms, carries `attempt`), `tool.started`, `tool.completed`, `tool.failed`, `agent.message`,
  `agent.failed`. All carry `turn_id`.
- Tokens are published from inside the model activity (worker-model); tool events from per-event
  activities (worker); turn events from the workflow via the `publish_event` activity.
- `GET /api/conversations/{id}/state` reads the channel seq **before** messages and actions, so
  any change missing from the state arrives as an event with a higher seq (some higher-seq events
  may already be reflected; applying them is idempotent).
- Web client (`hooks/useConversation.ts`): drop `seq <= last`; refetch on a gap; append tokens,
  resetting the partial text when `attempt` increases; refetch state on any event that changes
  durable state and on every (re)subscribe.

## Browser channel (Phase 7)

`browser:{session_id}` carries `browser.frame {session_id, frame_version, url}` and
`browser.mode`. Subscription tokens via `POST /api/realtime/subscribe_token
{browser_session_id}` after an ownership check. `browser.mode` is also published on the
conversation channel so the chat refreshes.

## User channel (Phase 9)

`user:{id}` carries `notification.created {notification_id, kind}`. Goal notifications also
publish `event.message` on the goal's conversation channel.
