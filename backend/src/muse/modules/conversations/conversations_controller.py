"""Queries for conversations and messages."""

import uuid

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.conversations.conversations_schema import (
    ConversationView,
    MessageView,
    Role,
)
from muse.shared.tables import conversations, messages


class ConversationsController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create(self, user_id: uuid.UUID, title: str | None) -> ConversationView:
        stmt = insert(conversations).values(user_id=user_id, title=title).returning(conversations)
        row = (await self._conn.execute(stmt)).mappings().one()
        return ConversationView.model_validate(dict(row))

    async def list_for_user(self, user_id: uuid.UUID) -> list[ConversationView]:
        stmt = (
            select(conversations)
            .where(conversations.c.user_id == user_id)
            .order_by(conversations.c.updated_at.desc())
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [ConversationView.model_validate(dict(r)) for r in rows]

    async def get(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False
    ) -> ConversationView | None:
        stmt = select(conversations).where(
            conversations.c.id == conversation_id, conversations.c.user_id == user_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self._conn.execute(stmt)).mappings().first()
        return ConversationView.model_validate(dict(row)) if row else None

    async def touch(self, conversation_id: uuid.UUID, title_if_empty: str | None = None) -> None:
        values: dict[str, object] = {"updated_at": func.now()}
        if title_if_empty is not None:
            values["title"] = func.coalesce(conversations.c.title, title_if_empty)
        await self._conn.execute(
            update(conversations).where(conversations.c.id == conversation_id).values(**values)
        )


class MessagesController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def append(self, conversation_id: uuid.UUID, role: Role, content: str) -> MessageView:
        # Callers hold the conversation row lock, so max(seq) + 1 cannot race.
        next_seq = (
            select(func.coalesce(func.max(messages.c.seq), 0) + 1)
            .where(messages.c.conversation_id == conversation_id)
            .scalar_subquery()
        )
        stmt = (
            insert(messages)
            .values(conversation_id=conversation_id, role=role, content=content, seq=next_seq)
            .returning(messages)
        )
        row = (await self._conn.execute(stmt)).mappings().one()
        return MessageView.model_validate(dict(row))

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> list[MessageView]:
        stmt = (
            select(messages)
            .where(messages.c.conversation_id == conversation_id)
            .order_by(messages.c.seq)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [MessageView.model_validate(dict(r)) for r in rows]

    async def recent(
        self, conversation_id: uuid.UUID, limit: int, *, before_seq: int
    ) -> list[MessageView]:
        stmt = (
            select(messages)
            .where(messages.c.conversation_id == conversation_id, messages.c.seq < before_seq)
            .order_by(messages.c.seq.desc())
            .limit(limit)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [MessageView.model_validate(dict(r)) for r in reversed(rows)]
