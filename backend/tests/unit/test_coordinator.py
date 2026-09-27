"""The agent reaches tools only through the gateway (TemporalDurability is transparent here)."""

import json
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from pydantic_ai.messages import ModelMessage, RetryPromptPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

from muse.agents.coordinator import build_coordinator
from muse.agents.deps import AgentDeps
from muse.agents.runtime import AgentRuntime, configure_agent_runtime
from muse.policy.engine import PolicyEngine
from muse.tools.specs import build_registry
from tests.fakes import FakeRecorder


def scripted(first_call_args: dict[str, object]) -> FunctionModel:
    """Streams: tool call first; after the tool returns, echo its output; after a retry, give up."""

    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        parts = list(messages[-1].parts)
        returns = [p for p in parts if isinstance(p, ToolReturnPart)]
        if returns:
            yield f"tool said {returns[0].content}"
        elif any(isinstance(p, RetryPromptPart) for p in parts):
            yield "gave up after retry"
        else:
            yield {0: DeltaToolCall(name="clock_now", json_args=json.dumps(first_call_args))}

    return FunctionModel(stream_function=respond)


@pytest.fixture
def recorder() -> Iterator[FakeRecorder]:
    recorder = FakeRecorder()
    configure_agent_runtime(
        AgentRuntime(
            registry=build_registry(), policy=PolicyEngine(), recorder=recorder, publisher=None
        )
    )
    yield recorder


def deps() -> AgentDeps:
    return AgentDeps(user_id=uuid.uuid4(), conversation_id=uuid.uuid4(), turn_id=uuid.uuid4())


async def test_tool_call_goes_through_gateway_and_is_recorded(recorder: FakeRecorder):
    agent = build_coordinator(scripted({"timezone": "Asia/Tokyo"}), build_registry(), "q")

    result = await agent.run("what time is it in Tokyo?", deps=deps())

    assert "Asia/Tokyo" in result.output
    [(proposal, decision)] = recorder.decisions
    assert proposal.tool == "clock.now"
    assert decision.kind.value == "ALLOW"


async def test_model_supplied_classification_is_rejected_not_executed(recorder: FakeRecorder):
    agent = build_coordinator(scripted({"risk": "READ_ONLY"}), build_registry(), "q")

    result = await agent.run("time?", deps=deps())

    assert result.output == "gave up after retry"
    assert recorder.decisions == []
    assert "tool.invalid_args" in recorder.event_types()
