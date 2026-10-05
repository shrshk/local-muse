"""Queries for notifications."""

import uuid
from typing import Any

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.notifications.budget import Preference, preference_for
from muse.modules.notifications.notifications_schema import NotificationView
from muse.shared.tables import notification_preferences, notifications


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
        importance: str = "normal",
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
                importance=importance,
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

    async def get_owned(
        self, user_id: uuid.UUID, notification_id: uuid.UUID
    ) -> NotificationView | None:
        stmt = select(notifications).where(
            notifications.c.id == notification_id, notifications.c.user_id == user_id
        )
        row = (await self._conn.execute(stmt)).mappings().first()
        return NotificationView.model_validate(dict(row)) if row else None

    async def pending_push(self, since_minutes: int, limit: int = 20) -> list[dict[str, Any]]:
        """Undispatched notifications, oldest first; older ones are never pushed."""
        stmt = (
            select(notifications)
            .where(
                notifications.c.push_status.is_(None),
                notifications.c.created_at
                > func.now() - text(f"interval '{int(since_minutes)} minutes'"),
            )
            .order_by(notifications.c.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [dict(r) for r in (await self._conn.execute(stmt)).mappings().all()]

    async def set_push_status(self, notification_id: uuid.UUID, push_status: str) -> None:
        await self._conn.execute(
            update(notifications)
            .where(notifications.c.id == notification_id)
            .values(push_status=push_status)
        )

    async def pushed_today(self, user_id: uuid.UUID, kind: str) -> int:
        stmt = select(func.count()).where(
            notifications.c.user_id == user_id,
            notifications.c.kind == kind,
            notifications.c.push_status == "sent",
            notifications.c.created_at > func.now() - text("interval '1 day'"),
        )
        count: int = (await self._conn.execute(stmt)).scalar_one()
        return count

    async def preference(self, user_id: uuid.UUID, kind: str) -> Preference:
        row = (
            (
                await self._conn.execute(
                    select(notification_preferences).where(
                        notification_preferences.c.user_id == user_id,
                        notification_preferences.c.kind == kind,
                    )
                )
            )
            .mappings()
            .first()
        )
        stored = Preference.model_validate(dict(row)) if row else None
        return preference_for(kind, stored)

    async def stored_preferences(self, user_id: uuid.UUID) -> list[Preference]:
        stmt = select(notification_preferences).where(notification_preferences.c.user_id == user_id)
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [Preference.model_validate(dict(r)) for r in rows]

    async def save_preference(self, user_id: uuid.UUID, pref: Preference) -> None:
        stmt = pg_insert(notification_preferences).values(
            user_id=user_id, kind=pref.kind, level=pref.level.value, daily_cap=pref.daily_cap
        )
        await self._conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "kind"],
                set_={
                    "level": stmt.excluded.level,
                    "daily_cap": stmt.excluded.daily_cap,
                    "updated_at": func.now(),
                },
            )
        )

    async def kinds_seen(self, user_id: uuid.UUID) -> set[str]:
        stmt = select(notifications.c.kind).where(notifications.c.user_id == user_id).distinct()
        kinds: list[str] = list((await self._conn.execute(stmt)).scalars().all())
        return set(kinds)
