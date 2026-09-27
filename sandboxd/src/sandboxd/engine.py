"""Docker access. The docker SDK is synchronous; every call runs in a worker thread."""

import asyncio
import io
import posixpath
import tarfile
import time
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound
from docker.models.containers import Container

from sandboxd.constraints import (
    LABEL,
    MAX_FILE_BYTES,
    MAX_OUTPUT_BYTES,
    SANDBOX_UID,
    container_name,
    create_kwargs,
    volume_name,
)

USER = f"{SANDBOX_UID}:{SANDBOX_UID}"


class SandboxMissing(Exception):
    pass


class DockerEngine:
    def __init__(self, base_url: str, timeout_seconds: float, image: str) -> None:
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._image = image
        self._client: docker.DockerClient | None = None

    def _docker(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.DockerClient(base_url=self._base_url, timeout=self._timeout)
        return self._client

    async def ping(self) -> bool:
        try:
            return bool(await asyncio.to_thread(lambda: self._docker().ping()))
        except (DockerException, OSError):
            return False

    async def running_keys(self) -> set[str]:
        def run() -> set[str]:
            found = self._docker().containers.list(filters={"label": f"{LABEL}=1"})
            return {c.labels.get(f"{LABEL}.key", "") for c in found}

        return await asyncio.to_thread(run)

    async def ensure(self, key: str) -> str:
        """Running container for key: reuse it, or create a fresh one on the key's volume."""

        def run() -> str:
            client = self._docker()
            try:
                existing = client.containers.get(container_name(key))
                if existing.status == "running":
                    return "running"
                existing.remove(force=True)
            except NotFound:
                pass
            client.containers.run(**create_kwargs(self._image, key))
            return "created"

        return await asyncio.to_thread(run)

    async def exec(self, key: str, cmd: str, timeout_s: int, cwd: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            container = self._get(key)
            started = time.monotonic()
            exit_code, (out, err) = container.exec_run(
                ["timeout", "-s", "KILL", str(timeout_s), "sh", "-c", cmd],
                user=USER,
                workdir=cwd,
                demux=True,
            )
            elapsed = time.monotonic() - started
            out, err = out or b"", err or b""
            truncated = len(out) > MAX_OUTPUT_BYTES or len(err) > MAX_OUTPUT_BYTES
            return {
                "stdout": out[:MAX_OUTPUT_BYTES].decode(errors="replace"),
                "stderr": err[:MAX_OUTPUT_BYTES].decode(errors="replace"),
                "exit_code": int(exit_code),
                "truncated": truncated,
                "timed_out": exit_code == 137 and elapsed >= timeout_s,
            }

        return await asyncio.to_thread(run)

    async def write_file(self, key: str, path: str, data: bytes) -> None:
        def run() -> None:
            container = self._get(key)
            directory, name = posixpath.split(path)
            container.exec_run(["mkdir", "-p", directory], user=USER)
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as tar:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.uid = info.gid = SANDBOX_UID
                info.mode = 0o644
                info.mtime = int(time.time())
                tar.addfile(info, io.BytesIO(data))
            container.put_archive(directory, archive.getvalue())

        await asyncio.to_thread(run)

    async def read_file(self, key: str, path: str) -> bytes:
        def run() -> bytes:
            stream, stat = self._get(key).get_archive(path)
            if stat["size"] > MAX_FILE_BYTES:
                raise ValueError("file too large")
            with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as tar:
                member = tar.next()
                if member is None or not member.isfile():
                    raise ValueError("not a regular file")
                extracted = tar.extractfile(member)
                assert extracted is not None
                return extracted.read()

        return await asyncio.to_thread(run)

    async def list_dir(self, key: str, path: str) -> list[dict[str, Any]]:
        def run() -> list[dict[str, Any]]:
            code, (out, _) = self._get(key).exec_run(
                ["find", path, "-mindepth", "1", "-maxdepth", "1", "-printf", r"%y\t%s\t%P\n"],
                user=USER,
                demux=True,
            )
            if code != 0:
                raise ValueError("not a directory")
            entries = []
            for line in (out or b"").decode(errors="replace").splitlines():
                kind, size, name = line.split("\t", 2)
                entries.append(
                    {"name": name, "kind": "dir" if kind == "d" else "file", "size": int(size)}
                )
            return sorted(entries, key=lambda e: e["name"])

        return await asyncio.to_thread(run)

    async def destroy(self, key: str) -> None:
        def run() -> None:
            try:
                self._docker().containers.get(container_name(key)).remove(force=True)
            except NotFound:
                pass

        await asyncio.to_thread(run)

    async def destroy_volume(self, key: str) -> None:
        def run() -> None:
            try:
                self._docker().volumes.get(volume_name(key)).remove()
            except NotFound:
                pass

        await asyncio.to_thread(run)

    def _get(self, key: str) -> Container:
        try:
            container = self._docker().containers.get(container_name(key))
        except NotFound as exc:
            raise SandboxMissing(key) from exc
        if container.status != "running":
            raise SandboxMissing(key)
        return container


__all__ = ["APIError", "DockerEngine", "DockerException", "SandboxMissing"]
