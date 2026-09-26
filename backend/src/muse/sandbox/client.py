"""HTTP client for sandboxd. Only the worker has a network route to it."""

from typing import Any

import httpx

from muse.shared.settings import Settings


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
