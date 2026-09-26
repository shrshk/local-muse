"""Queries for service heartbeats."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.health.health_schema import HeartbeatRow
from muse.shared.tables import service_heartbeats


class HeartbeatController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def upsert(self, service: str, status: str, detail: dict[str, Any]) -> None:
        stmt = insert(service_heartbeats).values(service=service, status=status, detail=detail)
        stmt = stmt.on_conflict_do_update(
            index_elements=[service_heartbeats.c.service],
            set_={"status": status, "detail": detail, "updated_at": func.now()},
        )
        await self._conn.execute(stmt)

    async def fetch(self, services: Sequence[str]) -> list[HeartbeatRow]:
        # Age is computed by the database clock, so container clock skew cannot fake freshness.
        age = func.extract("epoch", func.now() - service_heartbeats.c.updated_at)
        stmt = select(
            service_heartbeats.c.service,
            service_heartbeats.c.status,
            service_heartbeats.c.detail,
            age.label("age_seconds"),
        ).where(service_heartbeats.c.service.in_(services))
        rows = (await self._conn.execute(stmt)).all()
        return [
            HeartbeatRow(
                service=r.service,
                status=r.status,
                detail=r.detail,
                age_seconds=float(r.age_seconds),
            )
            for r in rows
        ]
