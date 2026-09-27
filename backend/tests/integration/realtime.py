"""A minimal Centrifugo client for tests: connect, subscribe to one conversation, collect events."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import websockets

from tests.integration.conftest import WEB_URL

WS_URL = WEB_URL.replace("http", "ws", 1) + "/connection/websocket"
Event = dict[str, Any]


class ConversationListener:
    def __init__(self, client: httpx.AsyncClient, conversation_id: str) -> None:
        self._client = client
        self._conversation_id = conversation_id
        self.events: list[Event] = []
        self._changed = asyncio.Condition()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "ConversationListener":
        connect = (await self._client.post("/api/realtime/token")).json()["token"]
        subscribe = (
            await self._client.post(
                "/api/realtime/subscribe_token", json={"conversation_id": self._conversation_id}
            )
        ).json()["token"]
        self._ws = await websockets.connect(WS_URL, origin=WEB_URL)  # type: ignore[arg-type]
        await self._ws.send(json.dumps({"id": 1, "connect": {"token": connect}}))
        channel = f"conversation:{self._conversation_id}"
        await self._ws.send(
            json.dumps({"id": 2, "subscribe": {"channel": channel, "token": subscribe}})
        )
        self._task = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._task:
            self._task.cancel()
        await self._ws.close()

    async def _read(self) -> None:
        async for frame in self._ws:
            for line in str(frame).splitlines():
                message = json.loads(line) if line.strip() else {}
                if message == {}:
                    await self._ws.send("{}")  # server ping
                    continue
                if "error" in message:
                    raise AssertionError(f"centrifugo error: {message}")
                pub = message.get("push", {}).get("pub")
                if pub:
                    async with self._changed:
                        self.events.append(pub["data"])
                        self._changed.notify_all()

    async def wait_for(self, predicate: Callable[[Event], bool]) -> Event:
        """Wrap in `asyncio.timeout(...)` at the call site."""
        async with self._changed:
            while True:
                for event in self.events:
                    if predicate(event):
                        return event
                await self._changed.wait()

    def of_type(self, event_type: str) -> list[Event]:
        return [e for e in self.events if e["type"] == event_type]
