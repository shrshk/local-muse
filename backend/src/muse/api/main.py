"""FastAPI app. Routers are transport only; handlers own the logic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from muse.agents.coordinator import Coordinator
from muse.api.routers import auth, conversations, health, models, realtime
from muse.models.factory import build_provider
from muse.modules.auth.auth_handler import AuthHandler
from muse.modules.conversations.conversations_handler import ConversationsHandler
from muse.modules.health.health_handler import HealthHandler
from muse.modules.health.probes import CentrifugoProbe, ModelProbe, PostgresProbe, TemporalProbe
from muse.modules.realtime.realtime_handler import RealtimeHandler
from muse.policy.engine import PolicyEngine
from muse.shared.db import create_engine
from muse.shared.logger import configure_logging, get_logger
from muse.shared.settings import get_settings
from muse.shared.temporal import TemporalClientProvider
from muse.tools.recorder import PostgresActionRecorder
from muse.tools.specs import build_registry

settings = get_settings()
configure_logging("backend", settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_engine(settings)
    http = httpx.AsyncClient(timeout=settings.probe_timeout_seconds)
    temporal = TemporalClientProvider(settings)
    provider = build_provider(settings, http)
    registry = build_registry()
    timeout = settings.probe_timeout_seconds

    app.state.model_provider = provider
    app.state.health_handler = HealthHandler(
        engine,
        probes=[
            PostgresProbe(engine, timeout),
            TemporalProbe(temporal, timeout),
            CentrifugoProbe(http, settings),
            ModelProbe(provider, timeout),
        ],
        stale_seconds=settings.heartbeat_stale_seconds,
    )
    app.state.realtime_handler = RealtimeHandler(settings)
    app.state.auth_handler = AuthHandler(engine, settings)
    app.state.conversations_handler = ConversationsHandler(
        engine,
        coordinator=Coordinator(provider.model(), registry),
        registry=registry,
        policy=PolicyEngine(),
        recorder=PostgresActionRecorder(engine),
        history_limit=settings.chat_history_messages,
    )
    logger.info("backend_ready", model=settings.model_name, mode=settings.local_muse_mode)
    yield
    await provider.aclose()
    await http.aclose()
    await engine.dispose()


app = FastAPI(title="Local Muse", version="0.2.0", lifespan=lifespan)
for router in (health.router, auth.router, conversations.router, models.router, realtime.router):
    app.include_router(router)
