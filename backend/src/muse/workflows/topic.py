"""TopicWorkflow: child of ConversationWorkflow, id `topic-<topic_id>`. One objective, one report.

Cancellation always records the outcome before the workflow ends (cleanup runs after the
cancellation is delivered; later phases also destroy the sandbox and close the browser here).
"""

import asyncio
import uuid
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from muse.workflows.approvals import ApprovalGate, run_with_approvals

with workflow.unsafe.imports_passed_through():
    import annotated_types  # noqa: F401  # pydantic imports it lazily; keep it out of the sandbox
    from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow
    from pydantic_ai.exceptions import AgentRunError
    from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart
    from pydantic_ai.usage import UsageLimits

    from muse.activities.approvals import ApprovalActivities, ApprovalDecisionInput
    from muse.activities.conversation import ConversationActivities
    from muse.activities.sandbox import ReleaseSandboxInput, SandboxActivities
    from muse.activities.topics import TopicActivities
    from muse.agents.deps import AgentDeps
    from muse.agents.instances import TOPIC_WORKER
    from muse.realtime.publisher import conversation_channel
    from muse.workflows.schema import (
        FinishTopicInput,
        ProfileContextInput,
        PublishEventInput,
        TopicInput,
        TopicResult,
    )

ACTIVITY_TIMEOUT = timedelta(seconds=15)
ACTIVITY_RETRY = RetryPolicy(maximum_attempts=10, initial_interval=timedelta(seconds=1))


@workflow.defn(name="TopicWorkflow")
class TopicWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = (TOPIC_WORKER,)

    def __init__(self) -> None:
        self._gate = ApprovalGate()

    @workflow.update
    async def decide_approval(self, decision: ApprovalDecisionInput) -> bool:
        applied = await workflow.execute_activity_method(
            ApprovalActivities.record_decision,
            decision,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=ACTIVITY_RETRY,
        )
        if applied:
            self._gate.record(decision.approval_id, decision.approved)
            await self._publish("approval.resolved", approval_id=str(decision.approval_id))
        return applied

    @decide_approval.validator
    def _validate_decision(self, decision: ApprovalDecisionInput) -> None:
        self._gate.check(decision.approval_id)

    @workflow.run
    async def run(self, topic: TopicInput) -> TopicResult:
        self._topic = topic
        try:
            return await self._work(topic)
        finally:
            # Always, including on cancellation: the container goes, the workspace volume stays.
            await workflow.execute_activity_method(
                SandboxActivities.release,
                ReleaseSandboxInput(sandbox_id=topic.topic_id),
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=ACTIVITY_RETRY,
            )

    async def _work(self, topic: TopicInput) -> TopicResult:
        await self._publish("topic.started")
        deps = AgentDeps(
            user_id=topic.user_id,
            conversation_id=topic.conversation_id,
            turn_id=topic.topic_id,
            topic_id=topic.topic_id,
            actor_id=f"topic:{topic.topic_id}",
            workflow_id=workflow.info().workflow_id,
            approval_ttl_s=topic.approval_timeout_s,
        )
        profile = await workflow.execute_activity_method(
            ConversationActivities.profile_context,
            ProfileContextInput(user_id=topic.user_id),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=ACTIVITY_RETRY,
        )
        history: list[ModelMessage] = (
            [ModelRequest(parts=[SystemPromptPart(content=profile)])] if profile else []
        )
        try:
            result = await run_with_approvals(
                TOPIC_WORKER,
                f"Objective: {topic.objective}",
                history,
                deps,
                UsageLimits(request_limit=topic.step_limit),
                self._gate,
                self._announce,
                timedelta(seconds=topic.approval_timeout_s),
            )
        except asyncio.CancelledError:
            await self._finish(FinishTopicInput(topic_id=topic.topic_id, status="cancelled"))
            await self._publish("topic.cancelled")
            raise
        except (AgentRunError, ActivityError) as exc:
            error = type(exc).__name__
            await self._finish(
                FinishTopicInput(topic_id=topic.topic_id, status="failed", error=error)
            )
            await self._publish("topic.failed", error=error)
            return TopicResult(
                topic_id=topic.topic_id, title=topic.title, status="failed", error=error
            )

        report = result.output
        await self._finish(
            FinishTopicInput(
                topic_id=topic.topic_id, status="completed", report=report.model_dump()
            )
        )
        await self._publish("topic.completed")
        return TopicResult(
            topic_id=topic.topic_id, title=topic.title, status="completed", summary=report.summary
        )

    async def _announce(self, approval_ids: list[uuid.UUID]) -> None:
        await self._publish(
            "approval.required", approval_ids=",".join(str(a) for a in approval_ids)
        )

    async def _finish(self, outcome: FinishTopicInput) -> None:
        await workflow.execute_activity_method(
            TopicActivities.finish,
            outcome,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=ACTIVITY_RETRY,
        )

    async def _publish(self, event_type: str, **data: str) -> None:
        try:
            await workflow.execute_activity_method(
                ConversationActivities.publish_event,
                PublishEventInput(
                    channel=conversation_channel(self._topic.conversation_id),
                    event_type=event_type,
                    data={"topic_id": str(self._topic.topic_id), **data},
                ),
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError:
            workflow.logger.warning("realtime_event_dropped", extra={"event_type": event_type})
