"""The agent reaches tools only through the gateway."""

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from muse.agents.coordinator import Coordinator
from muse.agents.deps import AgentDeps
from muse.policy.engine import PolicyEngine
from muse.tools.gateway import ToolGateway
from muse.tools.specs import build_registry
from tests.fakes import FakeRecorder, make_ctx


def last_parts(messages: list[ModelMessage]) -> list[object]:
    return list(messages[-1].parts)


def scripted(first_call_args: dict[str, object]) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        parts = last_parts(messages)
        returns = [p for p in parts if isinstance(p, ToolReturnPart)]
        if returns:
            return ModelResponse(parts=[TextPart(content=f"tool said {returns[0].content}")])
        if any(isinstance(p, RetryPromptPart) for p in parts):
            return ModelResponse(parts=[TextPart(content="gave up after retry")])
        return ModelResponse(parts=[ToolCallPart(tool_name="clock_now", args=first_call_args)])

    return FunctionModel(respond)


async def test_tool_call_goes_through_gateway_and_is_recorded():
    registry = build_registry()
    recorder = FakeRecorder()
    ctx = make_ctx()
    deps = AgentDeps(ctx=ctx, tools=ToolGateway(registry, PolicyEngine(), recorder, ctx))
    coordinator = Coordinator(scripted({"timezone": "Asia/Tokyo"}), registry)

    reply = await coordinator.reply("what time is it in Tokyo?", [], deps)

    assert "Asia/Tokyo" in reply
    [(proposal, decision)] = recorder.decisions
    assert proposal.tool == "clock.now"
    assert decision.kind.value == "ALLOW"


async def test_model_supplied_classification_is_rejected_not_executed():
    registry = build_registry()
    recorder = FakeRecorder()
    ctx = make_ctx()
    deps = AgentDeps(ctx=ctx, tools=ToolGateway(registry, PolicyEngine(), recorder, ctx))
    coordinator = Coordinator(scripted({"risk": "READ_ONLY"}), registry)

    reply = await coordinator.reply("time?", [], deps)

    assert reply == "gave up after retry"
    assert recorder.decisions == []
    assert "tool.invalid_args" in recorder.event_types()
