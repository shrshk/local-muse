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

## Phase 1 scope

Workers start, connect, and poll their queues with a single `ping` activity each (a Temporal
worker needs at least one registration). No workflows yet.
