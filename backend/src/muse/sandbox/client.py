"""HTTP client for sandboxd. Only the worker has a network route to it."""

import base64
import uuid
from typing import Any

import httpx

from muse.shared.settings import Settings

CLIENT_MARGIN_SECONDS = 15


class SandboxError(Exception):
    """sandboxd refused or failed. The message is safe to show the model."""


class SandboxClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http
        self._base_url = settings.sandboxd_url
        self._headers = {"Authorization": f"Bearer {settings.sandboxd_token}"}

    async def health(self) -> dict[str, Any]:
        response = await self._http.get(f"{self._base_url}/health", headers=self._headers)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    async def ensure(self, sandbox_id: uuid.UUID) -> dict[str, Any]:
        return await self._json("POST", "/sandboxes", json={"topic_id": str(sandbox_id)})

    async def exec(
        self, sandbox_id: uuid.UUID, cmd: str, timeout_s: int, cwd: str
    ) -> dict[str, Any]:
        return await self._json(
            "POST",
            f"/sandboxes/{sandbox_id}/exec",
            json={"cmd": cmd, "timeout_s": timeout_s, "cwd": cwd},
            timeout=timeout_s + CLIENT_MARGIN_SECONDS,
        )

    async def write_file(self, sandbox_id: uuid.UUID, path: str, data: bytes) -> None:
        await self._request(
            "PUT",
            f"/sandboxes/{sandbox_id}/files/{path}",
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )

    async def read_file(self, sandbox_id: uuid.UUID, path: str) -> bytes:
        return (await self._request("GET", f"/sandboxes/{sandbox_id}/files/{path}")).content

    async def list_dir(self, sandbox_id: uuid.UUID, path: str) -> list[dict[str, Any]]:
        response = await self._request(
            "GET", f"/sandboxes/{sandbox_id}/files", params={"path": path}
        )
        entries: list[dict[str, Any]] = response.json()
        return entries

    async def stage(self, sandbox_id: uuid.UUID, filename: str, data: bytes) -> str:
        body = {"filename": filename, "content_b64": base64.b64encode(data).decode()}
        return str((await self._json("POST", f"/sandboxes/{sandbox_id}/stage", json=body))["path"])

    async def destroy(self, sandbox_id: uuid.UUID) -> None:
        await self._request("DELETE", f"/sandboxes/{sandbox_id}")

    async def destroy_volume(self, sandbox_id: uuid.UUID) -> None:
        await self._request("DELETE", f"/sandboxes/{sandbox_id}/volume")

    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        body: dict[str, Any] = (await self._request(method, path, **kwargs)).json()
        return body

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {**self._headers, **kwargs.pop("headers", {})}
        timeout = kwargs.pop("timeout", 30)
        try:
            response = await self._http.request(
                method, f"{self._base_url}{path}", headers=headers, timeout=timeout, **kwargs
            )
        except httpx.HTTPError as exc:
            raise SandboxError(f"sandbox unreachable ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            raise SandboxError(f"sandbox refused ({response.status_code}): {response.text[:200]}")
        return response
