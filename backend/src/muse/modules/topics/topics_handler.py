"""Topic reads, cancellation, and user edits to topic memory."""

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio.service import RPCError, RPCStatusCode

from muse.modules.topics.topics_controller import TopicMemoryController, TopicsController
from muse.modules.topics.topics_schema import (
    ACTIVE_STATUSES,
    TopicMemoryView,
    TopicStatus,
    TopicView,
    UpdateTopicMemory,
)
from muse.shared.logger import get_logger
from muse.shared.temporal import TemporalClientProvider

logger = get_logger(__name__)


class TopicNotFound(Exception):
    pass


class TopicNotActive(Exception):
    pass


class StaleMemoryVersion(Exception):
    pass


class TopicsHandler:
    def __init__(self, engine: AsyncEngine, temporal: TemporalClientProvider) -> None:
        self._engine = engine
        self._temporal = temporal

    async def get(self, topic_id: uuid.UUID, user_id: uuid.UUID) -> TopicView:
        async with self._engine.connect() as conn:
            return await self._require(TopicsController(conn), topic_id, user_id)

    async def cancel(self, topic_id: uuid.UUID, user_id: uuid.UUID) -> TopicView:
        async with self._engine.begin() as conn:
            topics = TopicsController(conn)
            topic = await self._require(topics, topic_id, user_id)
            if topic.status not in ACTIVE_STATUSES:
                raise TopicNotActive(topic.status.value)
            if topic.status is TopicStatus.PENDING:
                # Not started yet: the workflow only claims pending rows, so this is enough.
                await topics.finish(topic_id, TopicStatus.CANCELLED, {"error": None})
                return await self._require(topics, topic_id, user_id)
        client = await self._temporal.get()
        try:
            await client.get_workflow_handle(f"topic-{topic_id}").cancel()
        except RPCError as exc:
            if exc.status is not RPCStatusCode.NOT_FOUND:
                raise
            logger.warning("topic_workflow_missing_on_cancel", topic_id=str(topic_id))
        return topic

    async def memory(self, topic_id: uuid.UUID, user_id: uuid.UUID) -> TopicMemoryView:
        async with self._engine.connect() as conn:
            await self._require(TopicsController(conn), topic_id, user_id)
            return await TopicMemoryController(conn).get(topic_id)

    async def update_memory(
        self, topic_id: uuid.UUID, user_id: uuid.UUID, body: UpdateTopicMemory
    ) -> TopicMemoryView:
        async with self._engine.begin() as conn:
            await self._require(TopicsController(conn), topic_id, user_id)
            updated = await TopicMemoryController(conn).replace(
                topic_id, body.document, body.version
            )
        if updated is None:
            raise StaleMemoryVersion(str(body.version))
        return updated

    async def _require(
        self, topics: TopicsController, topic_id: uuid.UUID, user_id: uuid.UUID
    ) -> TopicView:
        topic = await topics.get(topic_id, user_id)
        if topic is None:
            raise TopicNotFound(str(topic_id))
        return topic
