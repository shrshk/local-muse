"""ConversationWorkflow: one per conversation, id `conv-<conversation_id>`.

Messages arrive through the `send_message` Update (the client gets an ack once the message is
persisted). Turns run one at a time; model and tool I/O are activities via TemporalDurability.
Topics recorded by the topic.start tool are started as TopicWorkflow children after the turn;
their results come back as `event` messages that the coordinator relays in a turn of its own.
"""

import asyncio
import uuid
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, CancelledError, ChildWorkflowError

from muse.workflows.topic import TopicWorkflow

with workflow.unsafe.imports_passed_through():
    import annotated_types  # noqa: F401  # pydantic imports it lazily; keep it out of the sandbox
    from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow
    from pydantic_ai.exceptions import AgentRunError
    from pydantic_ai.messages import (
        ModelMessage,
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )
    from pydantic_ai.usage import UsageLimits

    from muse.activities.conversation import ConversationActivities
    from muse.activities.topics import TopicActivities
    from muse.agents.coordinator import MAX_REQUESTS_PER_TURN
    from muse.agents.deps import AgentDeps
    from muse.agents.instances import COORDINATOR
    from muse.agents.topic_worker import DEFAULT_STEP_LIMIT
    from muse.realtime.publisher import conversation_channel
    from muse.workflows.schema import (
        ClaimTopicsInput,
        ConversationState,
        ConversationStatus,
        HistoryItem,
        LoadTurnInput,
        PendingTurn,
        PersistMessageInput,
        PublishEventInput,
        SendMessageAck,
        SendMessageInput,
        TopicInput,
        TopicResult,
        TopicStart,
    )

IDLE_TIMEOUT = timedelta(hours=24)
MAX_PENDING = 5
PERSIST_TIMEOUT = timedelta(seconds=15)
PERSIST_RETRY = RetryPolicy(maximum_attempts=10, initial_interval=timedelta(seconds=1))
PUBLISH_TIMEOUT = timedelta(seconds=10)
PUBLISH_RETRY = RetryPolicy(maximum_attempts=3)


@workflow.defn(name="ConversationWorkflow")
class ConversationWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = (COORDINATOR,)

    @workflow.init
    def __init__(self, state: ConversationState) -> None:
        self._state = state
        self._queue: list[PendingTurn] = list(state.pending)
        self._running: PendingTurn | None = None
        self._last_error: str | None = None
        self._turns = 0
        self._active_topics: dict[uuid.UUID, TopicStart] = {}
        self._watchers: set[asyncio.Task[None]] = set()

    @workflow.run
    async def run(self, state: ConversationState) -> None:
        while True:
            try:
                await workflow.wait_condition(lambda: bool(self._queue), timeout=IDLE_TIMEOUT)
            except TimeoutError:
                await workflow.wait_condition(workflow.all_handlers_finished)
                if not self._queue and not self._active_topics:
                    return
                continue
            turn = self._queue.pop(0)
            self._running = turn
            await self._run_turn(turn)
            self._running = None
            self._turns += 1
            if self._should_continue_as_new():
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(self._state.model_copy(update={"pending": self._queue}))

    @workflow.update
    async def send_message(self, request: SendMessageInput) -> SendMessageAck:
        message = await workflow.execute_activity_method(
            ConversationActivities.persist_message,
            PersistMessageInput(
                message_id=workflow.uuid4(),
                conversation_id=self._state.conversation_id,
                role="user",
                content=request.content,
            ),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        turn = PendingTurn(turn_id=workflow.uuid4(), message_id=message.id, seq=message.seq)
        self._queue.append(turn)
        return SendMessageAck(message_id=message.id, seq=message.seq, turn_id=turn.turn_id)

    @send_message.validator
    def _validate_send(self, request: SendMessageInput) -> None:
        if len(self._queue) >= MAX_PENDING:
            raise ValueError("too many pending messages")

    @workflow.query
    def status(self) -> ConversationStatus:
        return ConversationStatus(
            running_turn_id=self._running.turn_id if self._running else None,
            pending_turn_ids=[t.turn_id for t in self._queue],
            active_topic_ids=list(self._active_topics),
            last_error=self._last_error,
        )

    async def _run_turn(self, turn: PendingTurn) -> None:
        await self._publish("agent.started", turn)
        context = await workflow.execute_activity_method(
            ConversationActivities.load_turn,
            LoadTurnInput(
                conversation_id=self._state.conversation_id,
                message_id=turn.message_id,
                history_limit=self._state.history_limit,
            ),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        deps = AgentDeps(
            user_id=self._state.user_id,
            conversation_id=self._state.conversation_id,
            turn_id=turn.turn_id,
            trigger="user" if turn.kind == "user" else "event",
        )
        try:
            result = await COORDINATOR.run(
                context.prompt,
                message_history=to_model_history(context.history),
                deps=deps,
                usage_limits=UsageLimits(request_limit=MAX_REQUESTS_PER_TURN),
            )
        except (AgentRunError, ActivityError) as exc:
            self._last_error = type(exc).__name__
            workflow.logger.warning("turn_failed", extra={"error": self._last_error})
            self._running = None
            await self._publish("agent.failed", turn, reason=self._last_error)
            return

        self._last_error = None
        reply = await workflow.execute_activity_method(
            ConversationActivities.persist_message,
            PersistMessageInput(
                message_id=workflow.uuid4(),
                conversation_id=self._state.conversation_id,
                role="assistant",
                content=result.output,
            ),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        await self._start_pending_topics()
        # Done before the final event, so a client reacting to it reads a finished state.
        self._running = None
        await self._publish("agent.message", turn, message_id=str(reply.id), seq=reply.seq)

    async def _start_pending_topics(self) -> None:
        claimed = await workflow.execute_activity_method(
            TopicActivities.claim_pending,
            ClaimTopicsInput(conversation_id=self._state.conversation_id),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        for topic in claimed:
            handle = await workflow.start_child_workflow(
                TopicWorkflow.run,
                TopicInput(
                    topic_id=topic.topic_id,
                    conversation_id=self._state.conversation_id,
                    user_id=self._state.user_id,
                    title=topic.title,
                    objective=topic.objective,
                    step_limit=DEFAULT_STEP_LIMIT,
                ),
                id=f"topic-{topic.topic_id}",
                # Cancel (not terminate) so the topic's cleanup always runs.
                parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
            )
            self._active_topics[topic.topic_id] = topic
            watcher = asyncio.create_task(self._watch_topic(topic, handle))
            self._watchers.add(watcher)
            watcher.add_done_callback(self._watchers.discard)

    async def _watch_topic(
        self, topic: TopicStart, handle: workflow.ChildWorkflowHandle[Any, TopicResult]
    ) -> None:
        try:
            result = await handle
        except ChildWorkflowError as exc:
            cancelled = isinstance(exc.cause, CancelledError)
            result = TopicResult(
                topic_id=topic.topic_id,
                title=topic.title,
                status="cancelled" if cancelled else "failed",
                error=None if cancelled else type(exc.cause).__name__,
            )
        await self._topic_finished(result)

    async def _topic_finished(self, result: TopicResult) -> None:
        text = {
            "completed": f'Topic "{result.title}" completed.\n\n{result.summary}',
            "failed": f'Topic "{result.title}" failed ({result.error}).',
            "cancelled": f'Topic "{result.title}" was cancelled.',
        }[result.status]
        message = await workflow.execute_activity_method(
            ConversationActivities.persist_message,
            PersistMessageInput(
                message_id=workflow.uuid4(),
                conversation_id=self._state.conversation_id,
                role="event",
                content=text,
            ),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        self._active_topics.pop(result.topic_id, None)
        turn = PendingTurn(
            turn_id=workflow.uuid4(), message_id=message.id, seq=message.seq, kind="topic_result"
        )
        await self._publish(
            "event.message", turn, topic_id=str(result.topic_id), status=result.status
        )
        if result.status == "completed":
            self._queue.append(turn)

    async def _publish(self, event_type: str, turn: PendingTurn, **data: Any) -> None:
        """Best effort: a lost event is a client-side gap, never a failed turn."""
        try:
            await workflow.execute_activity_method(
                ConversationActivities.publish_event,
                PublishEventInput(
                    channel=conversation_channel(self._state.conversation_id),
                    event_type=event_type,
                    data={"turn_id": str(turn.turn_id), **data},
                ),
                start_to_close_timeout=PUBLISH_TIMEOUT,
                retry_policy=PUBLISH_RETRY,
            )
        except ActivityError:
            workflow.logger.warning("realtime_event_dropped", extra={"event_type": event_type})

    def _should_continue_as_new(self) -> bool:
        # Children belong to this run; wait until none are active.
        if self._active_topics:
            return False
        return (
            self._turns >= self._state.turns_per_run
            or workflow.info().is_continue_as_new_suggested()
        )


def to_model_history(history: list[HistoryItem]) -> list[ModelMessage]:
    out: list[ModelMessage] = []
    for item in history:
        if item.role == "assistant":
            out.append(ModelResponse(parts=[TextPart(content=item.content)]))
        else:
            out.append(ModelRequest(parts=[UserPromptPart(content=as_prompt(item))]))
    return out


def as_prompt(item: HistoryItem) -> str:
    return f"[event] {item.content}" if item.role == "event" else item.content
