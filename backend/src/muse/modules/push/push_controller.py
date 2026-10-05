"""Queries for push subscriptions and the stored VAPID key."""

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.push.push_schema import Subscribe, SubscriptionView
from muse.shared.tables import app_keys, push_subscriptions

VAPID_KEY_NAME = "vapid_private_pem"
# A subscription that keeps failing is dropped; the browser re-subscribes on next open.
MAX_FAILURES = 5


class PushController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def upsert(self, user_id: uuid.UUID, sub: Subscribe, user_agent: str | None) -> bool:
        """False when the endpoint is already registered to another user."""
        insert = pg_insert(push_subscriptions).values(
            user_id=user_id,
            endpoint=sub.endpoint,
            p256dh=sub.keys.p256dh,
            auth=sub.keys.auth,
            user_agent=user_agent,
        )
        stmt = insert.on_conflict_do_update(
            index_elements=["endpoint"],
            set_={
                "p256dh": insert.excluded.p256dh,
                "auth": insert.excluded.auth,
                "user_agent": insert.excluded.user_agent,
                "failure_count": 0,
            },
            where=push_subscriptions.c.user_id == user_id,
        ).returning(push_subscriptions.c.id)
        return (await self._conn.execute(stmt)).first() is not None

    async def remove(self, user_id: uuid.UUID, endpoint: str) -> bool:
        stmt = delete(push_subscriptions).where(
            push_subscriptions.c.user_id == user_id, push_subscriptions.c.endpoint == endpoint
        )
        return bool((await self._conn.execute(stmt)).rowcount)

    async def for_user(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        stmt = select(push_subscriptions).where(push_subscriptions.c.user_id == user_id)
        return [dict(r) for r in (await self._conn.execute(stmt)).mappings().all()]

    async def views(self, user_id: uuid.UUID) -> list[SubscriptionView]:
        return [SubscriptionView.model_validate(r) for r in await self.for_user(user_id)]

    async def delete(self, subscription_id: uuid.UUID) -> None:
        await self._conn.execute(
            delete(push_subscriptions).where(push_subscriptions.c.id == subscription_id)
        )

    async def mark_success(self, subscription_id: uuid.UUID) -> None:
        await self._conn.execute(
            update(push_subscriptions)
            .where(push_subscriptions.c.id == subscription_id)
            .values(failure_count=0, last_success_at=func.now())
        )

    async def mark_failure(self, subscription_id: uuid.UUID) -> None:
        stmt = (
            update(push_subscriptions)
            .where(push_subscriptions.c.id == subscription_id)
            .values(failure_count=push_subscriptions.c.failure_count + 1)
            .returning(push_subscriptions.c.failure_count)
        )
        failures = (await self._conn.execute(stmt)).scalar_one_or_none()
        if failures is not None and failures >= MAX_FAILURES:
            await self.delete(subscription_id)

    async def vapid_pem(self) -> str | None:
        row = (
            await self._conn.execute(
                select(app_keys.c.value).where(app_keys.c.name == VAPID_KEY_NAME)
            )
        ).first()
        return str(row[0]) if row else None

    async def store_vapid_pem(self, pem: str) -> str:
        """Insert once; a concurrent first start keeps whichever key landed first."""
        stmt = pg_insert(app_keys).values(name=VAPID_KEY_NAME, value=pem)
        await self._conn.execute(stmt.on_conflict_do_nothing(index_elements=["name"]))
        stored = await self.vapid_pem()
        assert stored is not None
        return stored
