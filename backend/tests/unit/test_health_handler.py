import asyncio

import pytest

from muse.modules.health.health_handler import HealthHandler
from muse.modules.health.health_schema import ComponentStatus, HeartbeatRow
from muse.modules.health.probes import Probe, ProbeResult


class StaticProbe(Probe):
    def __init__(self, name: str, result: ProbeResult, delay: float = 0.0) -> None:
        super().__init__(timeout_seconds=0.05)
        self.name = name
        self._result = result
        self._delay = delay

    async def check(self) -> ProbeResult:
        await asyncio.sleep(self._delay)
        return self._result


@pytest.fixture
def handler() -> HealthHandler:
    return HealthHandler(engine=None, probes=[], stale_seconds=30)  # type: ignore[arg-type]


async def test_probe_timeout_reports_offline():
    result = await StaticProbe("slow", (ComponentStatus.ONLINE, None), delay=1).run()
    assert result.status is ComponentStatus.OFFLINE
    assert "timed out" in (result.detail or "")


async def test_probe_records_latency():
    result = await StaticProbe("fast", (ComponentStatus.ONLINE, None)).run()
    assert result.status is ComponentStatus.ONLINE
    assert result.latency_ms is not None


def test_missing_heartbeat_is_offline(handler: HealthHandler):
    component = handler.from_heartbeat("worker", None)
    assert component.status is ComponentStatus.OFFLINE
    assert component.detail == "no heartbeat"


def test_stale_heartbeat_is_offline_even_if_last_status_was_online(handler: HealthHandler):
    row = HeartbeatRow(service="worker", status="online", detail={}, age_seconds=31)
    assert handler.from_heartbeat("worker", row).status is ComponentStatus.OFFLINE


def test_fresh_heartbeat_carries_reported_status_and_detail(handler: HealthHandler):
    row = HeartbeatRow(
        service="sandboxd", status="degraded", detail={"detail": "docker: x"}, age_seconds=3
    )
    component = handler.from_heartbeat("sandboxd", row)
    assert component.status is ComponentStatus.DEGRADED
    assert component.detail == "docker: x"
