"""Queries for notifications."""

import uuid

from sqlalchemy import func, insert, select, update
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
