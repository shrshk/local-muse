"""Streams agent events to Centrifugo. Runs inside activities (model events live in the model
activity, tool events in per-event activities). Nothing here is durable; clients recover from
the API."""

import time
from collections.abc import AsyncIterable
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
)
from temporalio import activity

from muse.agents.deps import AgentDeps
from muse.agents.runtime import agent_runtime
from muse.realtime.publisher import RealtimePublisher, conversation_channel, topic_channel


class TokenBatcher:
    """Coalesces text deltas so one model response is a few dozen publishes, not hundreds."""

    FLUSH_CHARS = 48
    FLUSH_SECONDS = 0.15

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._size = 0
        self._last_flush = time.monotonic()

    def add(self, text: str) -> str | None:
        self._buffer.append(text)
        self._size += len(text)
        due = time.monotonic() - self._last_flush >= self.FLUSH_SECONDS
        return self.drain() if self._size >= self.FLUSH_CHARS or due else None

    def drain(self) -> str | None:
        if not self._buffer:
            return None
        text = "".join(self._buffer)
        self._buffer.clear()
        self._size = 0
        self._last_flush = time.monotonic()
        return text


class TurnEventPublisher:
    def __init__(self, publisher: RealtimePublisher, deps: AgentDeps, attempt: int) -> None:
        self._publisher = publisher
        # Topic runs stream to their own channel so they never mix into the chat bubble.
        self._channel = (
            topic_channel(deps.topic_id)
            if deps.topic_id
            else conversation_channel(deps.conversation_id)
        )
        self._turn = str(deps.turn_id)
        self._attempt = attempt
        self._tokens = TokenBatcher()

    async def consume(self, events: AsyncIterable[AgentStreamEvent]) -> None:
        async for event in events:
            await self._handle(event)
        await self._flush(self._tokens.drain())

    async def _handle(self, event: AgentStreamEvent) -> None:
        if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
            await self._flush(self._tokens.add(event.part.content))
        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
            await self._flush(self._tokens.add(event.delta.content_delta))
        elif isinstance(event, FunctionToolCallEvent):
            await self._emit(
                "tool.started", tool=event.part.tool_name, tool_call_id=event.part.tool_call_id
            )
        elif isinstance(event, FunctionToolResultEvent):
            part = event.part
            failed = isinstance(part, RetryPromptPart) or _is_error(part.content)
            await self._emit(
                "tool.failed" if failed else "tool.completed",
                tool=part.tool_name,
                tool_call_id=part.tool_call_id,
            )

    async def _flush(self, text: str | None) -> None:
        if text:
            await self._emit("agent.token", text=text, attempt=self._attempt)

    async def _emit(self, event_type: str, **data: Any) -> None:
        await self._publisher.publish(self._channel, event_type, {"turn_id": self._turn, **data})


def _is_error(content: Any) -> bool:
    return isinstance(content, dict) and "error" in content


async def publish_run_events(
    ctx: RunContext[AgentDeps], events: AsyncIterable[AgentStreamEvent]
) -> None:
    publisher = agent_runtime().publisher
    attempt = activity.info().attempt if activity.in_activity() else 1
    if publisher is None:
        async for _ in events:
            pass
        return
    await TurnEventPublisher(publisher, ctx.deps, attempt).consume(events)
