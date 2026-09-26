"""sandboxd API. Phase 1: health only."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request

from sandboxd.auth import require_token
from sandboxd.engine import DockerEngine
from sandboxd.logger import configure_logging, get_logger
from sandboxd.settings import Settings, get_settings

logger = get_logger(__name__)


def create_app(settings: Settings, engine: DockerEngine) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.engine = engine
        logger.info("sandboxd_ready")
        yield

    app = FastAPI(title="sandboxd", lifespan=lifespan, dependencies=[Depends(require_token)])

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        docker_ok = await request.app.state.engine.ping()
        return {"status": "ok", "docker": "ok" if docker_ok else "unreachable"}

    return app


def build() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    return create_app(settings, DockerEngine(settings.docker_url, settings.docker_timeout_seconds))
