"""sandboxd API. The only holder of the Docker socket; every route needs the bearer token."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from docker.errors import DockerException
from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response, status

from sandboxd.auth import require_token
from sandboxd.engine import DockerEngine, SandboxMissing
from sandboxd.handler import CapacityReached, FileTooLarge, SandboxHandler
from sandboxd.logger import configure_logging, get_logger
from sandboxd.paths import UnsafePath
from sandboxd.schema import (
    CreateSandbox,
    DirEntry,
    ExecRequest,
    ExecResult,
    SandboxView,
    StageRequest,
)
from sandboxd.settings import Settings, get_settings

logger = get_logger(__name__)


def handler(request: Request) -> SandboxHandler:
    sandbox_handler: SandboxHandler = request.app.state.handler
    return sandbox_handler


def create_app(settings: Settings, engine: DockerEngine) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.engine = engine
        app.state.handler = SandboxHandler(engine, settings.max_running_sandboxes)
        logger.info("sandboxd_ready")
        yield

    app = FastAPI(title="sandboxd", lifespan=lifespan, dependencies=[Depends(require_token)])

    @app.exception_handler(SandboxMissing)
    async def missing(_: Request, exc: SandboxMissing) -> Response:
        return Response(status_code=status.HTTP_404_NOT_FOUND, content="sandbox not running")

    @app.exception_handler(UnsafePath)
    async def unsafe(_: Request, exc: UnsafePath) -> Response:
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content=str(exc))

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        docker_ok = await request.app.state.engine.ping()
        return {"status": "ok", "docker": "ok" if docker_ok else "unreachable"}

    @app.post("/sandboxes", response_model=SandboxView)
    async def create(
        body: CreateSandbox, sandboxes: SandboxHandler = Depends(handler)
    ) -> SandboxView:
        try:
            return await sandboxes.create(body.topic_id)
        except CapacityReached as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except DockerException as exc:
            logger.exception("sandbox_create_failed", sandbox_id=str(body.topic_id))
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "docker error") from exc

    @app.post("/sandboxes/{sandbox_id}/exec", response_model=ExecResult)
    async def exec_cmd(
        sandbox_id: uuid.UUID, body: ExecRequest, sandboxes: SandboxHandler = Depends(handler)
    ) -> ExecResult:
        return await sandboxes.exec(sandbox_id, body)

    @app.put("/sandboxes/{sandbox_id}/files/{path:path}", status_code=status.HTTP_204_NO_CONTENT)
    async def write_file(
        sandbox_id: uuid.UUID,
        path: str,
        data: bytes = Body(media_type="application/octet-stream"),
        sandboxes: SandboxHandler = Depends(handler),
    ) -> None:
        try:
            await sandboxes.write_file(sandbox_id, path, data)
        except FileTooLarge as exc:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc

    @app.get("/sandboxes/{sandbox_id}/files/{path:path}")
    async def read_file(
        sandbox_id: uuid.UUID, path: str, sandboxes: SandboxHandler = Depends(handler)
    ) -> Response:
        try:
            data = await sandboxes.read_file(sandbox_id, path)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except DockerException as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such file") from exc
        return Response(content=data, media_type="application/octet-stream")

    @app.get("/sandboxes/{sandbox_id}/files", response_model=list[DirEntry])
    async def list_dir(
        sandbox_id: uuid.UUID, path: str = ".", sandboxes: SandboxHandler = Depends(handler)
    ) -> list[DirEntry]:
        try:
            return await sandboxes.list_dir(sandbox_id, path)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    @app.post("/sandboxes/{sandbox_id}/stage")
    async def stage(
        sandbox_id: uuid.UUID, body: StageRequest, sandboxes: SandboxHandler = Depends(handler)
    ) -> dict[str, str]:
        try:
            return {"path": await sandboxes.stage(sandbox_id, body)}
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    @app.delete("/sandboxes/{sandbox_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def destroy(sandbox_id: uuid.UUID, sandboxes: SandboxHandler = Depends(handler)) -> None:
        await sandboxes.destroy(sandbox_id)

    @app.delete("/sandboxes/{sandbox_id}/volume", status_code=status.HTTP_204_NO_CONTENT)
    async def destroy_volume(
        sandbox_id: uuid.UUID, sandboxes: SandboxHandler = Depends(handler)
    ) -> None:
        await sandboxes.destroy_volume(sandbox_id)

    return app


def build() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = DockerEngine(
        settings.docker_url, settings.docker_timeout_seconds, settings.sandbox_image
    )
    return create_app(settings, engine)
