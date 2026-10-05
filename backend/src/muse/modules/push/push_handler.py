"""Device registration for web push, and the server's VAPID key."""

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from muse.modules.notifications.notification_service import NotificationService
from muse.modules.push.push_controller import PushController
from muse.modules.push.push_schema import PublicKey, Subscribe, SubscriptionView
from muse.modules.push.sender import VapidKey, endpoint_allowed
from muse.realtime.publisher import RealtimePublisher
from muse.shared.settings import Settings


class SubscriptionRejected(ValueError):
    pass


async def load_vapid_key(engine: AsyncEngine) -> VapidKey:
    """Generated on first start and kept in Postgres; browsers bind subscriptions to it."""
    async with engine.begin() as conn:
        controller = PushController(conn)
        pem = await controller.vapid_pem() or await controller.store_vapid_pem(
            VapidKey.generate_pem()
        )
    return VapidKey(pem)


class PushHandler:
    def __init__(
        self,
        engine: AsyncEngine,
        key: VapidKey,
        settings: Settings,
        publisher: RealtimePublisher,
    ) -> None:
        self._engine = engine
        self._key = key
        self._settings = settings
        self._notifications = NotificationService(publisher)

    def public_key(self) -> PublicKey:
        return PublicKey(public_key=self._key.public_key)

    async def subscribe(self, user_id: uuid.UUID, sub: Subscribe, user_agent: str | None) -> None:
        if not endpoint_allowed(sub.endpoint, self._settings):
            raise SubscriptionRejected("not a supported push service")
        async with self._engine.begin() as conn:
            if not await PushController(conn).upsert(user_id, sub, (user_agent or "")[:300]):
                raise SubscriptionRejected("endpoint belongs to another user")

    async def unsubscribe(self, user_id: uuid.UUID, endpoint: str) -> bool:
        async with self._engine.begin() as conn:
            return await PushController(conn).remove(user_id, endpoint)

    async def devices(self, user_id: uuid.UUID) -> list[SubscriptionView]:
        async with self._engine.connect() as conn:
            return await PushController(conn).views(user_id)

    async def test(self, user_id: uuid.UUID) -> None:
        """A notification that always pushes, to check the whole path from the app."""
        async with self._engine.begin() as conn:
            notification = await self._notifications.notify(
                conn, user_id, "test", "Test notification", "Push works.", importance="high"
            )
        await self._notifications.announce(notification, user_id)
