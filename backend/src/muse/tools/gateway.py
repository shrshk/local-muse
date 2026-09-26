"""ToolGateway: the only path from a model's ToolIntent to an executor.

registry lookup → argument validation → classification → policy → record → execute → record.
"""

from pydantic import BaseModel, ValidationError

from muse.policy.engine import DecisionKind, PolicyEngine
from muse.shared.logger import get_logger
from muse.tools.errors import ToolExecutionError
from muse.tools.recorder import ActionRecorder
from muse.tools.registry import ToolRegistry
from muse.tools.schema import ActionProposal, ExecContext, Executor, ToolIntent, ToolResult

logger = get_logger(__name__)


class InvalidToolArgs(Exception):
    """Arguments failed validation. Returned to the model for one repair attempt; never executed."""


class ToolGateway:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PolicyEngine,
        recorder: ActionRecorder,
        ctx: ExecContext,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._recorder = recorder
        self._ctx = ctx
        self.proposals: list[tuple[ActionProposal, DecisionKind, ToolResult]] = []

    async def invoke(self, intent: ToolIntent) -> ToolResult:
        spec = self._registry.get(intent.tool)
        if spec is None:
            await self._recorder.audit("tool.unknown", self._ctx, {"tool": intent.tool})
            return ToolResult(ok=False, error=f"unknown tool {intent.tool!r}")

        try:
            args = spec.args_model.model_validate(intent.args)
        except ValidationError as exc:
            await self._recorder.audit(
                "tool.invalid_args", self._ctx, {"tool": spec.name, "errors": exc.error_count()}
            )
            raise InvalidToolArgs(_summarize(exc)) from exc

        proposal = self._registry.propose(spec, args, self._ctx)
        decision = await self._policy.evaluate(proposal, self._ctx)
        await self._recorder.record_decision(proposal, decision)

        if decision.kind is DecisionKind.ALLOW:
            result = await self._execute(spec.executor, args)
            await self._recorder.record_result(proposal, result)
        elif decision.kind is DecisionKind.DENY:
            result = ToolResult(ok=False, error=f"denied by policy: {decision.reason}")
        else:
            # Durable approval waits arrive with Temporal (Phase 6).
            result = ToolResult(ok=False, error="requires approval, which is not available yet")

        self.proposals.append((proposal, decision.kind, result))
        logger.info(
            "tool_invoked",
            tool=spec.name,
            action_id=str(proposal.action_id),
            decision=decision.kind.value,
            ok=result.ok,
        )
        return result

    async def _execute(self, executor: Executor, args: BaseModel) -> ToolResult:
        try:
            output = await executor(args, self._ctx)
        except ToolExecutionError as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(ok=True, output=output)


def _summarize(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc']) or 'args'}: {e['msg']}" for e in exc.errors()]
    return "; ".join(parts[:5])
