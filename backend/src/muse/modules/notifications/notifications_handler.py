"""Owner reads of notifications."""

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from muse.modules.notifications.notifications_controller import NotificationsController
from muse.modules.notifications.notifications_schema import NotificationView


class NotificationsHandler:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list_for_user(self, user_id: uuid.UUID) -> list[NotificationView]:
        async with self._engine.connect() as conn:
            return await NotificationsController(conn).list_for_user(user_id)

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
        async with self._engine.begin() as conn:
            return await NotificationsController(conn).mark_read(user_id, notification_id)
