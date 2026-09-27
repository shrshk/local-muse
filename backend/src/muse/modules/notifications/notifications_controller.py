"""Queries for notifications."""

import uuid
from typing import Any

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.notifications.notifications_schema import NotificationView
from muse.shared.tables import notifications


class NotificationsController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create(
        self,
        user_id: uuid.UUID,
        kind: str,
        title: str,
        body: str,
        conversation_id: uuid.UUID | None = None,
        goal_id: uuid.UUID | None = None,
        approval_id: uuid.UUID | None = None,
    ) -> NotificationView:
        stmt = (
            insert(notifications)
            .values(
                user_id=user_id,
                kind=kind,
                title=title,
                body=body,
                conversation_id=conversation_id,
                goal_id=goal_id,
                approval_id=approval_id,
            )
            .returning(notifications)
        )
        row = (await self._conn.execute(stmt)).mappings().one()
        return NotificationView.model_validate(dict(row))

    async def list_for_user(self, user_id: uuid.UUID, limit: int = 50) -> list[NotificationView]:
        stmt = (
            select(notifications)
            .where(notifications.c.user_id == user_id)
            .order_by(notifications.c.created_at.desc())
            .limit(limit)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [NotificationView.model_validate(dict(r)) for r in rows]

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
        stmt = (
            update(notifications)
            .where(notifications.c.id == notification_id, notifications.c.user_id == user_id)
            .values(read_at=func.coalesce(notifications.c.read_at, func.now()))
        )
        return bool((await self._conn.execute(stmt)).rowcount)

    async def pending_telegram(self, since_minutes: int, limit: int = 20) -> list[dict[str, Any]]:
        """Undelivered notifications, oldest first; older ones are never replayed."""
        stmt = (
            select(notifications)
            .where(
                notifications.c.telegram_status.is_(None),
                notifications.c.created_at
                > func.now() - text(f"interval '{since_minutes} minutes'"),
            )
            .order_by(notifications.c.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [dict(r) for r in (await self._conn.execute(stmt)).mappings().all()]

    async def set_telegram(self, notification_id: uuid.UUID, **values: Any) -> None:
        await self._conn.execute(
            update(notifications).where(notifications.c.id == notification_id).values(**values)
        )

    async def telegram_message_for_approval(self, approval_id: uuid.UUID) -> tuple[int, int] | None:
        stmt = select(notifications.c.telegram_chat_id, notifications.c.telegram_message_id).where(
            notifications.c.approval_id == approval_id,
            notifications.c.telegram_message_id.is_not(None),
        )
        row = (await self._conn.execute(stmt)).first()
        return (int(row[0]), int(row[1])) if row else None
