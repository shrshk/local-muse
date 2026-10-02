"""FastAPI app. Routers are transport only; handlers own the logic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from muse.api.routers import (
    approvals,
    auth,
    browser,
    conversations,
    goals,
    health,
    memory,
    models,
    realtime,
    topics,
)
from muse.models.factory import build_provider
from muse.modules.approvals.approvals_handler import ApprovalsHandler
from muse.modules.auth.auth_handler import AuthHandler
from muse.modules.browser.browser_handler import AllowlistHandler, BrowserHandler
from muse.modules.conversations.conversations_handler import ConversationsHandler
from muse.modules.goals.goals_handler import GoalsHandler
from muse.modules.health.health_handler import HealthHandler
from muse.modules.health.probes import CentrifugoProbe, ModelProbe, PostgresProbe, TemporalProbe
from muse.modules.memory.memory_handler import ProfileMemoryHandler
from muse.modules.notifications.notifications_handler import NotificationsHandler
from muse.modules.realtime.realtime_handler import RealtimeHandler
from muse.modules.topics.topics_handler import TopicsHandler
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
    provider = build_provider(settings, http)
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
    app.state.conversations_handler = ConversationsHandler(engine, temporal, settings)
    app.state.topics_handler = TopicsHandler(engine, temporal)
    app.state.profile_memory_handler = ProfileMemoryHandler(engine)
    app.state.approvals_handler = ApprovalsHandler(engine, temporal)
    app.state.browser_handler = BrowserHandler(engine, temporal)
    app.state.allowlist_handler = AllowlistHandler(engine)
    app.state.goals_handler = GoalsHandler(engine, temporal, settings)
    app.state.notifications_handler = NotificationsHandler(engine)
    logger.info(
        "backend_ready",
        model=settings.model_name,
        mode=settings.local_muse_mode,
    )
    yield
    await provider.aclose()
    await http.aclose()
    await engine.dispose()


app = FastAPI(title="Local Muse", version="0.4.0", lifespan=lifespan)
for router in (
    health.router,
    auth.router,
    conversations.router,
    topics.router,
    approvals.router,
    browser.router,
    goals.router,
    memory.router,
    models.router,
    realtime.router,
):
    app.include_router(router)
