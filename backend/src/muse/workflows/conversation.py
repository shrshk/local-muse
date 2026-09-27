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

from muse.workflows.approvals import ApprovalGate, BrowserModes, run_with_approvals
from muse.workflows.topic import TopicWorkflow

with workflow.unsafe.imports_passed_through():
    import annotated_types  # noqa: F401  # pydantic imports it lazily; keep it out of the sandbox
    from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow
    from pydantic_ai.exceptions import AgentRunError
    from pydantic_ai.messages import (
        ModelMessage,
        ModelRequest,
        ModelResponse,
        SystemPromptPart,
        TextPart,
        UserPromptPart,
    )
    from pydantic_ai.usage import UsageLimits

    from muse.activities.approvals import ApprovalActivities, ApprovalDecisionInput
    from muse.activities.browser import (
        BrowserActivities,
        BrowserCloseInput,
        BrowserHumanInputInput,
        BrowserModeInput,
    )
    from muse.activities.conversation import ConversationActivities
    from muse.activities.goals import ActivateGoalsInput, GoalActivities
    from muse.activities.sandbox import ReleaseSandboxInput, SandboxActivities
    from muse.activities.topics import TopicActivities
    from muse.agents.coordinator import MAX_REQUESTS_PER_TURN
    from muse.agents.deps import AgentDeps
    from muse.agents.instances import COORDINATOR, SUMMARIZER
    from muse.agents.topic_worker import DEFAULT_STEP_LIMIT
    from muse.realtime.publisher import conversation_channel
    from muse.workflows.schema import (
        ClaimTopicsInput,
        CompactionInput,
        ConversationState,
        ConversationStatus,
        HistoryItem,
        LoadTurnInput,
        PendingTurn,
        PersistMessageInput,
        PublishEventInput,
        SaveSummaryInput,
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
    __pydantic_ai_agents__ = (COORDINATOR, SUMMARIZER)

    @workflow.init
    def __init__(self, state: ConversationState) -> None:
        self._state = state
        self._queue: list[PendingTurn] = list(state.pending)
        self._running: PendingTurn | None = None
        self._last_error: str | None = None
        self._turns = 0
        self._active_topics: dict[uuid.UUID, TopicStart] = {}
        self._watchers: set[asyncio.Task[None]] = set()
        self._gate = ApprovalGate()
        self._browsers = BrowserModes()

    @workflow.run
    async def run(self, state: ConversationState) -> None:
        while True:
            try:
                await workflow.wait_condition(lambda: bool(self._queue), timeout=IDLE_TIMEOUT)
            except TimeoutError:
                await workflow.wait_condition(workflow.all_handlers_finished)
                if not self._queue and not self._active_topics:
                    await self._release_sandbox()
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

    @workflow.update
    async def decide_approval(self, decision: ApprovalDecisionInput) -> bool:
        applied = await workflow.execute_activity_method(
            ApprovalActivities.record_decision,
            decision,
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        if applied:
            self._gate.record(decision.approval_id, decision.approved)
            await self._publish_data(
                "approval.resolved",
                {"approval_id": str(decision.approval_id), "approved": decision.approved},
            )
        return applied

    @decide_approval.validator
    def _validate_decision(self, decision: ApprovalDecisionInput) -> None:
        self._gate.check(decision.approval_id)

    @workflow.update
    async def set_browser_mode(self, request: BrowserModeInput) -> None:
        await workflow.execute_activity_method(
            BrowserActivities.set_mode,
            request,
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        self._browsers.set(request.session_id, request.mode)

    @workflow.update
    async def browser_human_input(self, request: BrowserHumanInputInput) -> dict[str, Any]:
        result: dict[str, Any] = await workflow.execute_activity_method(
            BrowserActivities.human_input,
            request,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        return result

    @browser_human_input.validator
    def _validate_human_input(self, request: BrowserHumanInputInput) -> None:
        if not self._browsers.is_human(request.session_id):
            raise ValueError("take control of the browser first")

    @workflow.query
    def status(self) -> ConversationStatus:
        return ConversationStatus(
            running_turn_id=self._running.turn_id if self._running else None,
            pending_turn_ids=[t.turn_id for t in self._queue],
            active_topic_ids=list(self._active_topics),
            waiting_approval_ids=self._gate.waiting(),
            browser_modes=self._browsers.as_dict(),
            last_error=self._last_error,
        )

    async def _run_turn(self, turn: PendingTurn) -> None:
        await self._publish("agent.started", turn)
        context = await workflow.execute_activity_method(
            ConversationActivities.load_turn,
            LoadTurnInput(
                conversation_id=self._state.conversation_id,
                user_id=self._state.user_id,
                message_id=turn.message_id,
                history_limit=self._state.history_limit,
                token_budget=self._state.history_token_budget,
            ),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        deps = AgentDeps(
            user_id=self._state.user_id,
            conversation_id=self._state.conversation_id,
            turn_id=turn.turn_id,
            trigger="user" if turn.kind == "user" else "event",
            workflow_id=workflow.info().workflow_id,
            approval_ttl_s=self._state.approval_timeout_s,
        )

        async def announce(approval_ids: list[uuid.UUID]) -> None:
            await self._publish(
                "approval.required", turn, approval_ids=[str(a) for a in approval_ids]
            )

        try:
            result = await run_with_approvals(
                COORDINATOR,
                context.prompt,
                with_context(context.context, to_model_history(context.history)),
                deps,
                UsageLimits(request_limit=MAX_REQUESTS_PER_TURN),
                self._gate,
                announce,
                timedelta(seconds=self._state.approval_timeout_s),
                self._browsers,
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
        await workflow.execute_activity_method(
            GoalActivities.activate_pending,
            ActivateGoalsInput(conversation_id=self._state.conversation_id),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        # Done before the final event, so a client reacting to it reads a finished state.
        self._running = None
        await self._publish("agent.message", turn, message_id=str(reply.id), seq=reply.seq)
        if context.compact_up_to is not None:
            await self._compact(context.compact_up_to)

    async def _compact(self, up_to_seq: int) -> None:
        """Summarize turns that fell out of the history window. Best effort: a failure only
        means the next turn sees less history."""
        source = await workflow.execute_activity_method(
            ConversationActivities.load_compaction,
            CompactionInput(
                conversation_id=self._state.conversation_id,
                up_to_seq=up_to_seq,
                max_chars=self._state.history_token_budget * 8,
            ),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        if not source.transcript:
            return
        prompt = (
            f"Previous summary:\n{source.previous_summary or '(none)'}\n\n"
            f"New messages:\n{source.transcript}\n\nWrite the updated summary."
        )
        deps = AgentDeps(
            user_id=self._state.user_id,
            conversation_id=self._state.conversation_id,
            turn_id=workflow.uuid4(),
            actor_id="summarizer",
            trigger="event",
        )
        try:
            result = await SUMMARIZER.run(prompt, deps=deps)
        except (AgentRunError, ActivityError) as exc:
            workflow.logger.warning("compaction_failed", extra={"error": type(exc).__name__})
            return
        await workflow.execute_activity_method(
            ConversationActivities.save_summary,
            SaveSummaryInput(
                conversation_id=self._state.conversation_id,
                up_to_seq=up_to_seq,
                content=result.output,
            ),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )

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
                    approval_timeout_s=self._state.approval_timeout_s,
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
        await self._publish_data(event_type, {"turn_id": str(turn.turn_id), **data})

    async def _publish_data(self, event_type: str, data: dict[str, Any]) -> None:
        """Best effort: a lost event is a client-side gap, never a failed turn."""
        try:
            await workflow.execute_activity_method(
                ConversationActivities.publish_event,
                PublishEventInput(
                    channel=conversation_channel(self._state.conversation_id),
                    event_type=event_type,
                    data=data,
                ),
                start_to_close_timeout=PUBLISH_TIMEOUT,
                retry_policy=PUBLISH_RETRY,
            )
        except ActivityError:
            workflow.logger.warning("realtime_event_dropped", extra={"event_type": event_type})

    async def _release_sandbox(self) -> None:
        await workflow.execute_activity_method(
            BrowserActivities.close,
            BrowserCloseInput(session_id=self._state.conversation_id),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )
        await workflow.execute_activity_method(
            SandboxActivities.release,
            ReleaseSandboxInput(sandbox_id=self._state.conversation_id),
            start_to_close_timeout=PERSIST_TIMEOUT,
            retry_policy=PERSIST_RETRY,
        )

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


def with_context(context: str | None, history: list[ModelMessage]) -> list[ModelMessage]:
    if not context:
        return history
    return [ModelRequest(parts=[SystemPromptPart(content=context)]), *history]
