"""NotificationService (spec §17): attention-worthy events, separate from high-volume realtime.

Stores the notification (Postgres is the truth) and publishes `notification.created` on the
user's channel. The push dispatcher (`modules/push`) reads the same table as its outbox.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.notifications.notifications_controller import NotificationsController
from muse.modules.notifications.notifications_schema import NotificationView
from muse.realtime.publisher import RealtimePublisher


def user_channel(user_id: object) -> str:
    return f"user:{user_id}"


class NotificationService:
    def __init__(self, publisher: RealtimePublisher) -> None:
        self._publisher = publisher

    async def notify(
        self,
        conn: AsyncConnection,
        user_id: uuid.UUID,
        kind: str,
        title: str,
        body: str,
        conversation_id: uuid.UUID | None = None,
        goal_id: uuid.UUID | None = None,
        approval_id: uuid.UUID | None = None,
        importance: str = "normal",
    ) -> NotificationView:
        return await NotificationsController(conn).create(
            user_id, kind, title, body, conversation_id, goal_id, approval_id, importance
        )

    async def announce(self, notification: NotificationView, user_id: uuid.UUID) -> None:
        """Call after the transaction that stored it has committed."""
        await self._publisher.publish(
            user_channel(user_id),
            "notification.created",
            {"notification_id": str(notification.id), "kind": notification.kind},
        )
