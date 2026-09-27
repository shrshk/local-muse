"""Queries for profile memory and conversation summaries."""

import uuid
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.memory.memory_schema import ProfileFact
from muse.shared.tables import conversation_summaries, profile_memory


class ProfileMemoryController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list_for_user(self, user_id: uuid.UUID) -> list[ProfileFact]:
        stmt = (
            select(profile_memory)
            .where(profile_memory.c.user_id == user_id)
            .order_by(profile_memory.c.key)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [ProfileFact.model_validate(dict(r)) for r in rows]

    async def put(
        self, user_id: uuid.UUID, key: str, value: str, source: Literal["user", "agent"]
    ) -> ProfileFact:
        upsert = insert(profile_memory).values(user_id=user_id, key=key, value=value, source=source)
        stmt = upsert.on_conflict_do_update(
            constraint="pk_profile_memory",
            set_={"value": value, "source": source, "updated_at": func.now()},
        ).returning(profile_memory)
        return ProfileFact.model_validate(dict((await self._conn.execute(stmt)).mappings().one()))

    async def delete(self, user_id: uuid.UUID, key: str) -> bool:
        stmt = delete(profile_memory).where(
            profile_memory.c.user_id == user_id, profile_memory.c.key == key
        )
        return bool((await self._conn.execute(stmt)).rowcount)


class SummariesController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def latest(self, conversation_id: uuid.UUID) -> tuple[int, str] | None:
        stmt = (
            select(conversation_summaries.c.up_to_seq, conversation_summaries.c.content)
            .where(conversation_summaries.c.conversation_id == conversation_id)
            .order_by(conversation_summaries.c.up_to_seq.desc())
            .limit(1)
        )
        row = (await self._conn.execute(stmt)).first()
        return (row.up_to_seq, row.content) if row else None

    async def save(self, conversation_id: uuid.UUID, up_to_seq: int, content: str) -> None:
        stmt = insert(conversation_summaries).values(
            conversation_id=conversation_id, up_to_seq=up_to_seq, content=content
        )
        await self._conn.execute(stmt.on_conflict_do_nothing())
