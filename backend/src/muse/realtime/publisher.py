"""Centrifugo publisher. Best effort: a failed publish is logged, never raised.

Correctness never depends on delivery. The seq is allocated before publishing, so an event lost
while Centrifugo is down shows up to clients as a gap, which makes them re-fetch state.
"""

import datetime as dt
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from muse.modules.realtime.realtime_controller import RealtimeSeqController
from muse.shared.logger import get_logger
from muse.shared.settings import Settings

logger = get_logger(__name__)

MAX_MESSAGE_BYTES = 16 * 1024


def conversation_channel(conversation_id: object) -> str:
    return f"conversation:{conversation_id}"


class RealtimePublisher:
    def __init__(self, engine: AsyncEngine, http: httpx.AsyncClient, settings: Settings) -> None:
        self._engine = engine
        self._http = http
        self._url = f"{settings.centrifugo_api_url}/publish"
        self._headers = {"X-API-Key": settings.centrifugo_api_key}

    async def publish(self, channel: str, event_type: str, data: dict[str, Any]) -> int:
        async with self._engine.begin() as conn:
            seq = await RealtimeSeqController(conn).next(channel)
        envelope = {
            "type": event_type,
            "seq": seq,
            "ts": dt.datetime.now(dt.UTC).isoformat(),
            "data": data,
        }
        try:
            response = await self._http.post(
                self._url, json={"channel": channel, "data": envelope}, headers=self._headers
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(
                "realtime_publish_failed",
                channel=channel,
                event_type=event_type,
                seq=seq,
                error=type(exc).__name__,
            )
        return seq
