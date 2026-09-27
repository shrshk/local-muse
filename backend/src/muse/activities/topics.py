"""Topic activities: claim pending topics for the parent workflow, record outcomes."""

from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio import activity

from muse.modules.topics.topics_controller import TopicMemoryController, TopicsController
from muse.modules.topics.topics_schema import TopicMemoryDocument, TopicStatus
from muse.workflows.schema import ClaimTopicsInput, FinishTopicInput, TopicStart

MEMORY_WRITE_ATTEMPTS = 3


class TopicActivities:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @activity.defn(name="topic.claim_pending")
    async def claim_pending(self, request: ClaimTopicsInput) -> list[TopicStart]:
        async with self._engine.begin() as conn:
            claimed = await TopicsController(conn).claim_pending(request.conversation_id)
        return [TopicStart(topic_id=t.id, title=t.title, objective=t.objective) for t in claimed]

    @activity.defn(name="topic.finish")
    async def finish(self, request: FinishTopicInput) -> None:
        result = {"report": request.report, "error": request.error}
        async with self._engine.begin() as conn:
            await TopicsController(conn).finish(
                request.topic_id, TopicStatus(request.status), result
            )
        await self._update_memory(request)

    async def _update_memory(self, request: FinishTopicInput) -> None:
        # Optimistic write: a concurrent user edit wins the race, then we merge onto it.
        for _ in range(MEMORY_WRITE_ATTEMPTS):
            async with self._engine.begin() as conn:
                memory = TopicMemoryController(conn)
                current = await memory.get(request.topic_id)
                merged = merge_outcome(current.document, request)
                if await memory.replace(request.topic_id, merged, current.version):
                    return
        raise RuntimeError("topic memory kept changing; will retry")


def merge_outcome(doc: TopicMemoryDocument, outcome: FinishTopicInput) -> TopicMemoryDocument:
    update = doc.model_copy(deep=True)
    if outcome.status == "completed" and outcome.report:
        report = outcome.report
        update.summary = str(report.get("summary", update.summary))
        update.decisions += [str(d) for d in report.get("decisions", [])]
        update.sources += [str(s) for s in report.get("sources", [])]
        update.unfinished_work = [str(u) for u in report.get("unfinished_work", [])]
        update.next_actions = [str(n) for n in report.get("next_actions", [])]
    elif outcome.status == "cancelled":
        update.unfinished_work.append("Cancelled before completion.")
    else:
        update.failed_approaches.append(f"Run failed: {outcome.error}")
    return update
