"""FastAPI app. Routers are transport only; handlers own the logic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from muse.api.routers import health, realtime
from muse.modules.health.health_handler import HealthHandler
from muse.modules.health.probes import CentrifugoProbe, ModelProbe, PostgresProbe, TemporalProbe
from muse.modules.realtime.realtime_handler import RealtimeHandler
from muse.shared.db import create_engine
from muse.shared.logger import configure_logging, get_logger
from muse.shared.settings import get_settings
from muse.shared.temporal import TemporalClientProvider

settings = get_settings()
configure_logging("backend", settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_engine(settings)
    http = httpx.AsyncClient(timeout=settings.probe_timeout_seconds)
    temporal = TemporalClientProvider(settings)
    timeout = settings.probe_timeout_seconds

    app.state.health_handler = HealthHandler(
        engine,
        probes=[
            PostgresProbe(engine, timeout),
            TemporalProbe(temporal, timeout),
            CentrifugoProbe(http, settings),
            ModelProbe(http, settings),
        ],
        stale_seconds=settings.heartbeat_stale_seconds,
    )
    app.state.realtime_handler = RealtimeHandler(settings)
    logger.info("backend_ready")
    yield
    await http.aclose()
    await engine.dispose()


app = FastAPI(title="Local Muse", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(realtime.router)
