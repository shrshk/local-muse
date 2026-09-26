"""Direct health probes. Each is time-boxed and catches only the failures it expects."""

import asyncio
import time
from abc import ABC, abstractmethod

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio.service import RPCError

from muse.modules.health.health_schema import ComponentHealth, ComponentStatus
from muse.sandbox.client import SandboxClient
from muse.shared.settings import Settings
from muse.shared.temporal import TemporalClientProvider

ProbeResult = tuple[ComponentStatus, str | None]


class Probe(ABC):
    name: str

    def __init__(self, timeout_seconds: float) -> None:
        self._timeout = timeout_seconds

    async def run(self) -> ComponentHealth:
        started = time.perf_counter()
        try:
            status, detail = await asyncio.wait_for(self.check(), self._timeout)
        except TimeoutError:
            status, detail = ComponentStatus.OFFLINE, f"timed out after {self._timeout}s"
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return ComponentHealth(name=self.name, status=status, detail=detail, latency_ms=latency_ms)

    @abstractmethod
    async def check(self) -> ProbeResult: ...


class PostgresProbe(Probe):
    name = "postgres"

    def __init__(self, engine: AsyncEngine, timeout_seconds: float) -> None:
        super().__init__(timeout_seconds)
        self._engine = engine

    async def check(self) -> ProbeResult:
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError) as exc:
            return ComponentStatus.OFFLINE, type(exc).__name__
        return ComponentStatus.ONLINE, None


class TemporalProbe(Probe):
    name = "temporal"

    def __init__(self, provider: TemporalClientProvider, timeout_seconds: float) -> None:
        super().__init__(timeout_seconds)
        self._provider = provider

    async def check(self) -> ProbeResult:
        try:
            client = await self._provider.get()
            healthy = await client.service_client.check_health()
        except (RuntimeError, RPCError, OSError) as exc:
            return ComponentStatus.OFFLINE, type(exc).__name__
        if not healthy:
            return ComponentStatus.DEGRADED, "health check returned not serving"
        return ComponentStatus.ONLINE, None


class CentrifugoProbe(Probe):
    name = "centrifugo"

    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        super().__init__(settings.probe_timeout_seconds)
        self._http = http
        self._settings = settings

    async def check(self) -> ProbeResult:
        # The info call needs the API key, so this also proves the backend can publish.
        try:
            response = await self._http.post(
                f"{self._settings.centrifugo_api_url}/info",
                json={},
                headers={"X-API-Key": self._settings.centrifugo_api_key},
            )
        except httpx.HTTPError as exc:
            return ComponentStatus.OFFLINE, type(exc).__name__
        if response.status_code != httpx.codes.OK:
            return ComponentStatus.DEGRADED, f"api returned {response.status_code}"
        return ComponentStatus.ONLINE, None


class ProcessProbe(Probe):
    """Liveness of the reporting process itself: if it runs, it is online."""

    def __init__(self, name: str, detail: str) -> None:
        super().__init__(timeout_seconds=1.0)
        self.name = name
        self._detail = detail

    async def check(self) -> ProbeResult:
        return ComponentStatus.ONLINE, self._detail


class SandboxdProbe(Probe):
    name = "sandboxd"

    def __init__(self, client: SandboxClient, timeout_seconds: float) -> None:
        super().__init__(timeout_seconds)
        self._client = client

    async def check(self) -> ProbeResult:
        try:
            body = await self._client.health()
        except (httpx.HTTPError, ValueError) as exc:
            return ComponentStatus.OFFLINE, type(exc).__name__
        if body.get("docker") != "ok":
            return ComponentStatus.DEGRADED, f"docker: {body.get('docker')}"
        return ComponentStatus.ONLINE, None


class ModelProbe(Probe):
    name = "model"

    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        super().__init__(settings.probe_timeout_seconds)
        self._http = http
        self._settings = settings

    async def check(self) -> ProbeResult:
        try:
            response = await self._http.get(f"{self._settings.model_base_url}/api/tags")
            response.raise_for_status()
            models = {m["name"] for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return ComponentStatus.OFFLINE, f"ollama unreachable ({type(exc).__name__})"
        wanted = self._settings.model_name
        if wanted in models or f"{wanted}:latest" in models:
            return ComponentStatus.ONLINE, wanted
        return ComponentStatus.DEGRADED, f"run: ollama pull {wanted}"
