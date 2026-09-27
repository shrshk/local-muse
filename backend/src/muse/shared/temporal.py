"""Temporal client. PydanticAIPlugin supplies the payload converter both sides must share."""

import asyncio

from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from temporalio.client import Client

from muse.shared.settings import Settings


async def connect_temporal(settings: Settings) -> Client:
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        plugins=[PydanticAIPlugin()],
    )


class TemporalClientProvider:
    """Lazily connected, so the API starts even when Temporal is still booting."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> Client:
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = await connect_temporal(self._settings)
        return self._client
