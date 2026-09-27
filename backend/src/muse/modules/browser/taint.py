"""Conversation-level data taint: once logged-in content was read, onward writes need approval.

Coarse on purpose. The model can copy page text into any argument, so the policy keys on "this
conversation has seen authenticated content", not on what an argument happens to contain.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from muse.policy.classification import DataClassification
from muse.shared.tables import artifacts, data_taint


class TaintController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def mark(self, conversation_id: uuid.UUID, source: str) -> None:
        stmt = insert(data_taint).values(
            conversation_id=conversation_id,
            classification=DataClassification.AUTHENTICATED.value,
            source=source,
        )
        await self._conn.execute(stmt.on_conflict_do_nothing())

    async def is_tainted(self, conversation_id: uuid.UUID) -> bool:
        stmt = select(data_taint.c.conversation_id).where(
            data_taint.c.conversation_id == conversation_id
        )
        return (await self._conn.execute(stmt)).first() is not None

    async def artifact_classification(self, artifact_id: uuid.UUID) -> str | None:
        stmt = select(artifacts.c.classification).where(artifacts.c.id == artifact_id)
        value: str | None = (await self._conn.execute(stmt)).scalar_one_or_none()
        return value


class PostgresTaintStore:
    """The policy engine's view (see policy/engine.py `TaintStore`)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def is_tainted(self, conversation_id: uuid.UUID) -> bool:
        async with self._engine.connect() as conn:
            return await TaintController(conn).is_tainted(conversation_id)

    async def artifact_classification(self, artifact_id: uuid.UUID) -> str | None:
        async with self._engine.connect() as conn:
            return await TaintController(conn).artifact_classification(artifact_id)

    async def mark(self, conversation_id: uuid.UUID, source: str) -> None:
        async with self._engine.begin() as conn:
            await TaintController(conn).mark(conversation_id, source)
