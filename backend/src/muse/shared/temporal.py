"""Lazily connected Temporal client, so the API starts even when Temporal is still booting."""

import asyncio

from temporalio.client import Client

from muse.shared.settings import Settings


class TemporalClientProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> Client:
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = await Client.connect(
                        self._settings.temporal_address,
                        namespace=self._settings.temporal_namespace,
                    )
        return self._client
