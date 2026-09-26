"""Periodic heartbeat rows, so the backend can see workers and sandboxd without a network route."""

import asyncio
import pathlib
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from muse.modules.health.health_controller import HeartbeatController
from muse.modules.health.probes import Probe
from muse.shared.logger import get_logger

logger = get_logger(__name__)

# Touched after each successful write; the Compose healthcheck reads its mtime.
HEARTBEAT_FILE = pathlib.Path("/tmp/heartbeat")


class HeartbeatReporter:
    def __init__(
        self, engine: AsyncEngine, probes: Sequence[Probe], interval_seconds: float
    ) -> None:
        self._engine = engine
        self._probes = probes
        self._interval = interval_seconds

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.report_once()
            try:
                await asyncio.wait_for(stop.wait(), self._interval)
            except TimeoutError:
                pass

    async def report_once(self) -> None:
        results = await asyncio.gather(*(p.run() for p in self._probes))
        try:
            async with self._engine.begin() as conn:
                controller = HeartbeatController(conn)
                for r in results:
                    await controller.upsert(r.name, r.status.value, {"detail": r.detail})
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("heartbeat_write_failed", error=type(exc).__name__)
            return
        await asyncio.to_thread(HEARTBEAT_FILE.touch)
