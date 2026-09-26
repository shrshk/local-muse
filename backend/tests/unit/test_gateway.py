import pytest

from muse.policy.engine import Decision, DecisionKind, PolicyEngine
from muse.tools.gateway import InvalidToolArgs, ToolGateway
from muse.tools.schema import ActionProposal, ExecContext, ToolIntent
from muse.tools.specs import build_registry
from tests.fakes import FakeRecorder, make_ctx


class FixedPolicy(PolicyEngine):
    def __init__(self, decision: Decision) -> None:
        self._decision = decision

    async def evaluate(self, action: ActionProposal, ctx: ExecContext) -> Decision:
        return self._decision


def gateway(policy: PolicyEngine | None = None) -> tuple[ToolGateway, FakeRecorder]:
    recorder = FakeRecorder()
    return ToolGateway(build_registry(), policy or PolicyEngine(), recorder, make_ctx()), recorder


async def test_allowed_tool_executes_and_is_recorded():
    gw, recorder = gateway()
    result = await gw.invoke(ToolIntent(tool="clock.now", args={"timezone": "UTC"}))

    assert result.ok
    [(proposal, decision)] = recorder.decisions
    assert decision.kind is DecisionKind.ALLOW
    assert proposal.tool == "clock.now"
    assert proposal.risk == "READ_ONLY"
    assert [r.ok for _, r in recorder.results] == [True]


async def test_unknown_tool_is_denied_and_audited_without_a_proposal():
    gw, recorder = gateway()
    result = await gw.invoke(ToolIntent(tool="shell.exec", args={"cmd": "rm -rf /"}))

    assert not result.ok
    assert recorder.event_types() == ["tool.unknown"]
    assert recorder.decisions == []


async def test_invalid_args_never_execute():
    gw, recorder = gateway()
    with pytest.raises(InvalidToolArgs, match="risk"):
        await gw.invoke(ToolIntent(tool="clock.now", args={"risk": "READ_ONLY"}))

    assert recorder.event_types() == ["tool.invalid_args"]
    assert recorder.results == []


async def test_denied_action_is_recorded_but_not_executed():
    gw, recorder = gateway(FixedPolicy(Decision.deny("test")))
    result = await gw.invoke(ToolIntent(tool="clock.now", args={}))

    assert not result.ok
    assert "denied" in (result.error or "")
    assert len(recorder.decisions) == 1
    assert recorder.results == []


async def test_require_approval_is_not_executed():
    gw, recorder = gateway(FixedPolicy(Decision(kind=DecisionKind.REQUIRE_APPROVAL)))
    result = await gw.invoke(ToolIntent(tool="clock.now", args={}))

    assert not result.ok
    assert recorder.results == []


async def test_executor_failure_is_a_recorded_tool_error():
    gw, recorder = gateway()
    result = await gw.invoke(ToolIntent(tool="clock.now", args={"timezone": "Mars/Olympus"}))

    assert not result.ok
    assert [r.ok for _, r in recorder.results] == [False]
