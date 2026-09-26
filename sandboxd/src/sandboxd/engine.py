"""Docker engine access. All container constraints will be applied here, never by callers."""

import asyncio

import docker
from docker.errors import DockerException


class DockerEngine:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._client: docker.DockerClient | None = None

    def _get_client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.DockerClient(base_url=self._base_url, timeout=self._timeout)
        return self._client

    async def ping(self) -> bool:
        try:
            return bool(await asyncio.to_thread(lambda: self._get_client().ping()))
        except (DockerException, OSError):
            return False
