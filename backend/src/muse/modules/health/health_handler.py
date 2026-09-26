"""Aggregates direct probes and worker heartbeats into one report."""

import asyncio
import datetime as dt
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from muse.modules.health.health_controller import HeartbeatController
from muse.modules.health.health_schema import (
    ComponentHealth,
    ComponentStatus,
    HealthReport,
    HeartbeatRow,
)
from muse.modules.health.probes import Probe
from muse.shared.logger import get_logger

logger = get_logger(__name__)

# Components the backend cannot reach directly; workers report them via heartbeats.
HEARTBEAT_SERVICES = ("worker", "worker-model", "sandboxd")


class HealthHandler:
    def __init__(self, engine: AsyncEngine, probes: Sequence[Probe], stale_seconds: float) -> None:
        self._engine = engine
        self._probes = probes
        self._stale_seconds = stale_seconds

    async def report(self) -> HealthReport:
        direct, heartbeats = await asyncio.gather(
            asyncio.gather(*(p.run() for p in self._probes)),
            self._heartbeat_components(),
        )
        components = [
            ComponentHealth(name="backend", status=ComponentStatus.ONLINE),
            *direct,
            *heartbeats,
        ]
        overall = (
            ComponentStatus.ONLINE
            if all(c.status is ComponentStatus.ONLINE for c in components)
            else ComponentStatus.DEGRADED
        )
        return HealthReport(
            status=overall, components=components, checked_at=dt.datetime.now(dt.UTC)
        )

    async def _heartbeat_components(self) -> list[ComponentHealth]:
        try:
            async with self._engine.connect() as conn:
                rows = await HeartbeatController(conn).fetch(HEARTBEAT_SERVICES)
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("heartbeat_read_failed", error=type(exc).__name__)
            return [
                ComponentHealth(
                    name=s, status=ComponentStatus.OFFLINE, detail="postgres unavailable"
                )
                for s in HEARTBEAT_SERVICES
            ]
        by_service = {r.service: r for r in rows}
        return [self.from_heartbeat(s, by_service.get(s)) for s in HEARTBEAT_SERVICES]

    def from_heartbeat(self, service: str, row: HeartbeatRow | None) -> ComponentHealth:
        if row is None:
            return ComponentHealth(
                name=service, status=ComponentStatus.OFFLINE, detail="no heartbeat"
            )
        if row.age_seconds > self._stale_seconds:
            return ComponentHealth(
                name=service,
                status=ComponentStatus.OFFLINE,
                detail=f"last heartbeat {int(row.age_seconds)}s ago",
            )
        return ComponentHealth(
            name=service,
            status=ComponentStatus(row.status),
            detail=row.detail.get("detail"),
        )
