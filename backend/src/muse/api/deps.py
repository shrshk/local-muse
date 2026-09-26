"""FastAPI dependencies. Handlers are built once in the lifespan and read from app state."""

from fastapi import Request

from muse.modules.health.health_handler import HealthHandler
from muse.modules.realtime.realtime_handler import RealtimeHandler

# Single-owner app. Replaced by session auth when login lands (Phase 2).
OWNER_ID = "owner"


def health_handler(request: Request) -> HealthHandler:
    handler: HealthHandler = request.app.state.health_handler
    return handler


def realtime_handler(request: Request) -> RealtimeHandler:
    handler: RealtimeHandler = request.app.state.realtime_handler
    return handler


def current_user_id() -> str:
    return OWNER_ID
