"""Sandbox lifecycle and operations. One container per key (topic or conversation) at a time."""

import base64
import binascii
import posixpath
import re
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sandboxd.constraints import MAX_FILE_BYTES
from sandboxd.engine import DockerEngine
from sandboxd.logger import get_logger
from sandboxd.paths import resolve
from sandboxd.schema import DirEntry, ExecRequest, ExecResult, SandboxView, StageRequest

logger = get_logger(__name__)

SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


class CapacityReached(Exception):
    pass


class FileTooLarge(ValueError):
    pass


class SandboxHandler:
    """Capacity counts running containers. At capacity, the least recently used idle container
    is evicted (its /workspace volume is kept, so nothing is lost); only when every running
    sandbox is busy is a new one refused. Use tracking is in memory: after a restart, untracked
    sandboxes count as the oldest."""

    def __init__(self, engine: DockerEngine, max_running: int) -> None:
        self._engine = engine
        self._max_running = max_running
        self._last_used: dict[str, float] = {}
        self._busy: Counter[str] = Counter()

    async def create(self, key: uuid.UUID) -> SandboxView:
        name = str(key)
        running = await self._engine.running_keys()
        if name not in running and len(running) >= self._max_running:
            await self._evict_one(running)
        status = await self._engine.ensure(name)
        self._last_used[name] = time.monotonic()
        logger.info("sandbox_ready", sandbox_id=name, status=status)
        return SandboxView(sandbox_id=key, status=status)

    async def _evict_one(self, running: set[str]) -> None:
        idle = [k for k in running if not self._busy[k]]
        if not idle:
            raise CapacityReached(f"all {len(running)} sandboxes are busy")
        victim = min(idle, key=lambda k: self._last_used.get(k, 0.0))
        await self._engine.destroy(victim)
        self._last_used.pop(victim, None)
        logger.info("sandbox_evicted", sandbox_id=victim)

    @asynccontextmanager
    async def _using(self, key: uuid.UUID) -> AsyncIterator[str]:
        name = str(key)
        self._busy[name] += 1
        try:
            yield name
        finally:
            self._busy[name] -= 1
            self._last_used[name] = time.monotonic()

    async def exec(self, key: uuid.UUID, request: ExecRequest) -> ExecResult:
        async with self._using(key) as name:
            result = await self._engine.exec(
                name, request.cmd, request.timeout_s, resolve(request.cwd)
            )
        logger.info("sandbox_exec", sandbox_id=str(key), exit_code=result["exit_code"])
        return ExecResult.model_validate(result)

    async def write_file(self, key: uuid.UUID, path: str, data: bytes) -> None:
        if len(data) > MAX_FILE_BYTES:
            raise FileTooLarge(f"max {MAX_FILE_BYTES} bytes")
        async with self._using(key) as name:
            await self._engine.write_file(name, resolve(path), data)

    async def read_file(self, key: uuid.UUID, path: str) -> bytes:
        async with self._using(key) as name:
            return await self._engine.read_file(name, resolve(path))

    async def list_dir(self, key: uuid.UUID, path: str) -> list[DirEntry]:
        async with self._using(key) as name:
            entries = await self._engine.list_dir(name, resolve(path))
        return [DirEntry.model_validate(e) for e in entries]

    async def stage(self, key: uuid.UUID, request: StageRequest) -> str:
        """Trusted copy-in: only the worker's stager calls this, with artifact bytes it owns."""
        try:
            data = base64.b64decode(request.content_b64, validate=True)
        except binascii.Error as exc:
            raise ValueError("content is not valid base64") from exc
        name = SAFE_FILENAME.sub("_", posixpath.basename(request.filename)) or "artifact"
        path = f"incoming/{name}"
        await self.write_file(key, path, data)
        return path

    async def destroy(self, key: uuid.UUID) -> None:
        await self._engine.destroy(str(key))
        logger.info("sandbox_destroyed", sandbox_id=str(key))

    async def destroy_volume(self, key: uuid.UUID) -> None:
        await self._engine.destroy(str(key))
        await self._engine.destroy_volume(str(key))
        logger.info("sandbox_volume_destroyed", sandbox_id=str(key))
