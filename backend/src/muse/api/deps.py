"""FastAPI dependencies. Handlers are built once in the lifespan and read from app state."""

from fastapi import Cookie, Depends, HTTPException, Request, status

from muse.models.provider import ModelProvider
from muse.modules.auth.auth_handler import SESSION_COOKIE, AuthHandler, InvalidSession
from muse.modules.auth.auth_schema import Principal
from muse.modules.conversations.conversations_handler import ConversationsHandler
from muse.modules.health.health_handler import HealthHandler
from muse.modules.realtime.realtime_handler import RealtimeHandler


def health_handler(request: Request) -> HealthHandler:
    handler: HealthHandler = request.app.state.health_handler
    return handler


def realtime_handler(request: Request) -> RealtimeHandler:
    handler: RealtimeHandler = request.app.state.realtime_handler
    return handler


def auth_handler(request: Request) -> AuthHandler:
    handler: AuthHandler = request.app.state.auth_handler
    return handler


def conversations_handler(request: Request) -> ConversationsHandler:
    handler: ConversationsHandler = request.app.state.conversations_handler
    return handler


def model_provider(request: Request) -> ModelProvider:
    provider: ModelProvider = request.app.state.model_provider
    return provider


def current_user(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    auth: AuthHandler = Depends(auth_handler),
) -> Principal:
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not logged in")
    try:
        return auth.sessions.decode(session)
    except InvalidSession as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired or invalid") from exc
