"""ToolGateway: the only path from a model's ToolIntent to an executor.

registry lookup → argument validation → classification → policy → record → execute → record.
REQUIRE_APPROVAL does not execute: it records a pending approval, and the workflow waits. When
the approved call comes back, the gateway runs it once, under the original action_id.
"""

import dataclasses
import uuid

from pydantic import BaseModel, ValidationError

from muse.modules.approvals.approvals_schema import ApprovalStatus
from muse.policy.engine import Decision, DecisionKind, PolicyEngine
from muse.shared.logger import get_logger
from muse.tools.approvals import ApprovalStore
from muse.tools.errors import ToolDeferred, ToolExecutionError
from muse.tools.recorder import ActionRecorder
from muse.tools.registry import ToolRegistry
from muse.tools.schema import (
    ActionProposal,
    ExecContext,
    Executor,
    ToolIntent,
    ToolResult,
    ToolServices,
    ToolSpec,
)

logger = get_logger(__name__)


class InvalidToolArgs(Exception):
    """Arguments failed validation. Returned to the model for one repair attempt; never executed."""


class ToolGateway:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PolicyEngine,
        recorder: ActionRecorder,
        services: ToolServices,
        ctx: ExecContext,
        approvals: ApprovalStore | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._recorder = recorder
        self._services = services
        self._ctx = ctx
        self._approvals = approvals

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

        proposal = self._registry.propose(spec, args, self._ctx, self._services)
        decision = await self._policy.evaluate(proposal, self._ctx)

        if decision.kind is DecisionKind.REQUIRE_APPROVAL:
            result = await self._approval_path(spec, args, proposal, decision)
        else:
            await self._recorder.record_decision(proposal, decision)
            if decision.kind is DecisionKind.ALLOW:
                result = await self._run(spec, args, proposal)
            else:
                result = ToolResult(ok=False, error=f"denied by policy: {decision.reason}")

        logger.info(
            "tool_invoked",
            tool=spec.name,
            action_id=str(proposal.action_id),
            decision=decision.kind.value,
            rule=decision.rule,
            ok=result.ok,
            pending_approval=str(result.pending_approval) if result.pending_approval else None,
        )
        return result

    async def _approval_path(
        self, spec: ToolSpec, args: BaseModel, proposal: ActionProposal, decision: Decision
    ) -> ToolResult:
        workflow_id = self._ctx.workflow_id
        if self._approvals is None or workflow_id is None:
            await self._recorder.record_decision(proposal, decision)
            return ToolResult(ok=False, error="requires approval, which is not available here")

        existing = await self._approvals.open_for(proposal.approval_key, workflow_id)
        if existing is not None and existing.status is ApprovalStatus.APPROVED:
            original = proposal.model_copy(update={"action_id": existing.action_id})
            if await self._approvals.consume(existing.id):
                return await self._run(spec, args, original)
            if not existing.has_result and spec.idempotent:
                # Retry after a crash mid-execution: same action_id, executor dedupes on it.
                return await self._run(spec, args, original)
            if not existing.has_result:
                return ToolResult(
                    ok=False, error="outcome unknown; a non-idempotent action is not retried"
                )
        if existing is not None and existing.status is ApprovalStatus.PENDING:
            return ToolResult(ok=False, pending_approval=existing.id, error="awaiting approval")

        await self._recorder.record_decision(proposal, decision)
        approval_id = await self._approvals.request(
            proposal, decision.reason or "needs approval", workflow_id, self._ctx.approval_ttl_s
        )
        await self._recorder.audit(
            "approval.requested", self._ctx, {"approval_id": str(approval_id)}, proposal.action_id
        )
        return ToolResult(ok=False, pending_approval=approval_id, error="awaiting approval")

    async def _run(self, spec: ToolSpec, args: BaseModel, proposal: ActionProposal) -> ToolResult:
        result = await self._execute(spec.executor, args, proposal.action_id)
        await self._recorder.record_result(proposal, result)
        return result

    async def _execute(
        self, executor: Executor, args: BaseModel, action_id: uuid.UUID
    ) -> ToolResult:
        ctx = dataclasses.replace(self._ctx, action_id=action_id)
        try:
            output = await executor(args, ctx, self._services)
        except ToolExecutionError as exc:
            return ToolResult(ok=False, error=str(exc))
        except ToolDeferred as exc:
            return ToolResult(ok=False, error=str(exc), deferred=exc.metadata)
        return ToolResult(ok=True, output=output)


def _summarize(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc']) or 'args'}: {e['msg']}" for e in exc.errors()]
    return "; ".join(parts[:5])
