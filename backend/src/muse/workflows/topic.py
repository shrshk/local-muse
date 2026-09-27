"""TopicWorkflow: child of ConversationWorkflow, id `topic-<topic_id>`. One objective, one report.

Cancellation always records the outcome before the workflow ends (cleanup runs after the
cancellation is delivered; later phases also destroy the sandbox and close the browser here).
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    import annotated_types  # noqa: F401  # pydantic imports it lazily; keep it out of the sandbox
    from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow
    from pydantic_ai.exceptions import AgentRunError
    from pydantic_ai.usage import UsageLimits

    from muse.activities.conversation import ConversationActivities
    from muse.activities.topics import TopicActivities
    from muse.agents.deps import AgentDeps
    from muse.agents.instances import TOPIC_WORKER
    from muse.realtime.publisher import conversation_channel
    from muse.workflows.schema import (
        FinishTopicInput,
        PublishEventInput,
        TopicInput,
        TopicResult,
    )

ACTIVITY_TIMEOUT = timedelta(seconds=15)
ACTIVITY_RETRY = RetryPolicy(maximum_attempts=10, initial_interval=timedelta(seconds=1))


@workflow.defn(name="TopicWorkflow")
class TopicWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = (TOPIC_WORKER,)

    @workflow.run
    async def run(self, topic: TopicInput) -> TopicResult:
        self._topic = topic
        await self._publish("topic.started")
        deps = AgentDeps(
            user_id=topic.user_id,
            conversation_id=topic.conversation_id,
            turn_id=topic.topic_id,
            topic_id=topic.topic_id,
            actor_id=f"topic:{topic.topic_id}",
        )
        try:
            result = await TOPIC_WORKER.run(
                f"Objective: {topic.objective}",
                deps=deps,
                usage_limits=UsageLimits(request_limit=topic.step_limit),
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
