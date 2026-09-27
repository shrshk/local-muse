import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
    ToolReturnPart,
)

from muse.agents.deps import AgentDeps
from muse.agents.events import TokenBatcher, TurnEventPublisher


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, channel: str, event_type: str, data: dict[str, Any]) -> int:
        self.events.append((channel, event_type, data))
        return len(self.events)


async def stream(*events: AgentStreamEvent) -> AsyncIterator[AgentStreamEvent]:
    for e in events:
        yield e


@pytest.fixture
def deps() -> AgentDeps:
    return AgentDeps(user_id=uuid.uuid4(), conversation_id=uuid.uuid4(), turn_id=uuid.uuid4())


def test_batcher_holds_small_deltas_and_flushes_on_size(monkeypatch: pytest.MonkeyPatch):
    batcher = TokenBatcher()
    monkeypatch.setattr(TokenBatcher, "FLUSH_SECONDS", 60.0)
    assert batcher.add("Hel") is None
    assert batcher.add("lo " * 20) == "Hel" + "lo " * 20
    assert batcher.drain() is None


async def test_tokens_are_batched_and_the_tail_is_flushed(deps: AgentDeps):
    publisher = FakePublisher()
    events = [PartStartEvent(index=0, part=TextPart(content="Hi"))] + [
        PartDeltaEvent(index=0, delta=TextPartDelta(content_delta="x")) for _ in range(5)
    ]
    await TurnEventPublisher(publisher, deps, attempt=2).consume(stream(*events))  # type: ignore[arg-type]

    tokens = [d for _, t, d in publisher.events if t == "agent.token"]
    assert "".join(d["text"] for d in tokens) == "Hixxxxx"
    assert all(d["attempt"] == 2 and d["turn_id"] == str(deps.turn_id) for d in tokens)
    assert publisher.events[0][0] == f"conversation:{deps.conversation_id}"


async def test_tool_events_map_to_started_and_completed(deps: AgentDeps):
    publisher = FakePublisher()
    call = ToolCallPart(tool_name="clock_now", args={}, tool_call_id="c1")
    ok = ToolReturnPart(tool_name="clock_now", content={"iso": "x"}, tool_call_id="c1")
    err = ToolReturnPart(tool_name="clock_now", content={"error": "bad"}, tool_call_id="c2")
    await TurnEventPublisher(publisher, deps, attempt=1).consume(  # type: ignore[arg-type]
        stream(
            FunctionToolCallEvent(part=call),
            FunctionToolResultEvent(part=ok),
            FunctionToolResultEvent(part=err),
        )
    )

    assert [t for _, t, _ in publisher.events] == ["tool.started", "tool.completed", "tool.failed"]
