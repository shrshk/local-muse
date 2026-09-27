"""Queries for topics and topic memory."""

import uuid
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.topics.topics_schema import (
    ACTIVE_STATUSES,
    TopicMemoryDocument,
    TopicMemoryView,
    TopicStatus,
    TopicView,
)
from muse.shared.tables import topic_memory, topics


class TopicsController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID, title: str, objective: str
    ) -> TopicView:
        stmt = (
            insert(topics)
            .values(
                conversation_id=conversation_id,
                user_id=user_id,
                title=title,
                objective=objective,
                status=TopicStatus.PENDING.value,
            )
            .returning(topics)
        )
        return TopicView.model_validate(dict((await self._conn.execute(stmt)).mappings().one()))

    async def count_active(self, conversation_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            topics.c.conversation_id == conversation_id,
            topics.c.status.in_([s.value for s in ACTIVE_STATUSES]),
        )
        count: int = (await self._conn.execute(stmt)).scalar_one()
        return count

    async def claim_pending(self, conversation_id: uuid.UUID) -> list[TopicView]:
        """Pending → running. Idempotent: a retried call finds nothing left to claim."""
        stmt = (
            update(topics)
            .where(
                topics.c.conversation_id == conversation_id,
                topics.c.status == TopicStatus.PENDING.value,
            )
            .values(
                status=TopicStatus.RUNNING.value,
                workflow_id=func.concat("topic-", topics.c.id),
                updated_at=func.now(),
            )
            .returning(topics)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [TopicView.model_validate(dict(r)) for r in rows]

    async def finish(
        self, topic_id: uuid.UUID, status: TopicStatus, result: dict[str, Any]
    ) -> None:
        await self._conn.execute(
            update(topics)
            .where(topics.c.id == topic_id)
            .values(
                status=status.value, result=result, updated_at=func.now(), finished_at=func.now()
            )
        )

    async def get(self, topic_id: uuid.UUID, user_id: uuid.UUID) -> TopicView | None:
        stmt = select(topics).where(topics.c.id == topic_id, topics.c.user_id == user_id)
        row = (await self._conn.execute(stmt)).mappings().first()
        return TopicView.model_validate(dict(row)) if row else None

    async def running_for_user(self, user_id: uuid.UUID) -> list[TopicView]:
        stmt = (
            select(topics)
            .where(
                topics.c.user_id == user_id,
                topics.c.status.in_([s.value for s in ACTIVE_STATUSES]),
            )
            .order_by(topics.c.created_at)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [TopicView.model_validate(dict(r)) for r in rows]

    async def list_for_conversation(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[TopicView]:
        stmt = (
            select(topics)
            .where(topics.c.conversation_id == conversation_id, topics.c.user_id == user_id)
            .order_by(topics.c.created_at)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [TopicView.model_validate(dict(r)) for r in rows]


class TopicMemoryController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create(self, topic_id: uuid.UUID, document: TopicMemoryDocument) -> None:
        await self._conn.execute(
            insert(topic_memory).values(topic_id=topic_id, document=document.model_dump())
        )

    async def get(self, topic_id: uuid.UUID) -> TopicMemoryView:
        stmt = select(topic_memory).where(topic_memory.c.topic_id == topic_id)
        row = (await self._conn.execute(stmt)).mappings().one()
        return TopicMemoryView.model_validate(dict(row))

    async def replace(
        self, topic_id: uuid.UUID, document: TopicMemoryDocument, expected_version: int | None
    ) -> TopicMemoryView | None:
        """None when expected_version is stale (someone else wrote first)."""
        stmt = update(topic_memory).where(topic_memory.c.topic_id == topic_id)
        if expected_version is not None:
            stmt = stmt.where(topic_memory.c.version == expected_version)
        stmt = stmt.values(
            document=document.model_dump(),
            version=topic_memory.c.version + 1,
            updated_at=func.now(),
        ).returning(topic_memory)
        row = (await self._conn.execute(stmt)).mappings().first()
        return TopicMemoryView.model_validate(dict(row)) if row else None
