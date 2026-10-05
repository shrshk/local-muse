"""Owner reads of notifications."""

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from muse.modules.notifications.budget import (
    ALWAYS_PUSH,
    Feedback,
    Level,
    Preference,
    apply_feedback,
)
from muse.modules.notifications.notifications_controller import NotificationsController
from muse.modules.notifications.notifications_schema import NotificationView


class NotificationNotFound(LookupError):
    pass


class NotTunable(ValueError):
    """Approvals (and tests) always push; their level cannot be lowered."""


class NotificationsHandler:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list_for_user(self, user_id: uuid.UUID) -> list[NotificationView]:
        async with self._engine.connect() as conn:
            return await NotificationsController(conn).list_for_user(user_id)

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
        async with self._engine.begin() as conn:
            return await NotificationsController(conn).mark_read(user_id, notification_id)

    async def get(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> NotificationView:
        async with self._engine.connect() as conn:
            view = await NotificationsController(conn).get_owned(user_id, notification_id)
        if view is None:
            raise NotificationNotFound(str(notification_id))
        return view

    async def feedback(
        self, user_id: uuid.UUID, notification_id: uuid.UUID, signal: Feedback
    ) -> Preference:
        """ "More / less / none like this" moves that kind's level; trusted code, no model."""
        async with self._engine.begin() as conn:
            notifications = NotificationsController(conn)
            view = await notifications.get_owned(user_id, notification_id)
            if view is None:
                raise NotificationNotFound(str(notification_id))
            if view.kind in ALWAYS_PUSH:
                raise NotTunable(view.kind)
            pref = apply_feedback(await notifications.preference(user_id, view.kind), signal)
            await notifications.save_preference(user_id, pref)
            return pref

    async def preferences(self, user_id: uuid.UUID) -> list[Preference]:
        async with self._engine.connect() as conn:
            notifications = NotificationsController(conn)
            stored = {p.kind for p in await notifications.stored_preferences(user_id)}
            # Kinds that exist for this user, plus goals; not features that have not shipped.
            seen = await notifications.kinds_seen(user_id)
            kinds = sorted(({"goal"} | stored | seen) - ALWAYS_PUSH)
            return [await notifications.preference(user_id, kind) for kind in kinds]

    async def set_preference(
        self, user_id: uuid.UUID, kind: str, level: Level, daily_cap: int
    ) -> Preference:
        if kind in ALWAYS_PUSH:
            raise NotTunable(kind)
        pref = Preference(kind=kind, level=level, daily_cap=daily_cap)
        async with self._engine.begin() as conn:
            await NotificationsController(conn).save_preference(user_id, pref)
        return pref
