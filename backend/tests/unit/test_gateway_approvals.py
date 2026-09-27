"""REQUIRE_APPROVAL through the gateway, with an in-memory approval store."""

import uuid
from dataclasses import dataclass, replace
from typing import Any

from pydantic import JsonValue

from muse.modules.approvals.approvals_schema import ApprovalStatus
from muse.policy.engine import PolicyEngine
from muse.tools.approvals import OpenApproval
from muse.tools.gateway import ToolGateway
from muse.tools.registry import ToolRegistry
from muse.tools.schema import (
    ActionProposal,
    ExecContext,
    Executor,
    ToolIntent,
    ToolServices,
)
from muse.tools.specs import build_registry
from tests.fakes import FakeRecorder, make_ctx

SEND = ToolIntent(tool="outbox.send", args={"recipient": "a@example.com", "body": "hi"})


@dataclass
class Row:
    key: str
    workflow: str
    action_id: uuid.UUID
    status: ApprovalStatus = ApprovalStatus.PENDING
    consumed: bool = False


class FakeApprovals:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Row] = {}

    async def open_for(self, approval_key: str, workflow_id: str) -> OpenApproval | None:
        for approval_id, row in reversed(self.rows.items()):
            if (row.key, row.workflow) != (approval_key, workflow_id):
                continue
            if row.status is ApprovalStatus.PENDING or (
                row.status is ApprovalStatus.APPROVED and not row.consumed
            ):
                return OpenApproval(
                    id=approval_id,
                    action_id=row.action_id,
                    status=row.status,
                    consumed=row.consumed,
                    has_result=False,
                )
        return None

    async def request(
        self, proposal: ActionProposal, reason: str, workflow_id: str, ttl_seconds: int
    ) -> uuid.UUID:
        approval_id = uuid.uuid4()
        self.rows[approval_id] = Row(proposal.approval_key, workflow_id, proposal.action_id)
        return approval_id

    async def consume(self, approval_id: uuid.UUID) -> bool:
        if self.rows[approval_id].consumed:
            return False
        self.rows[approval_id].consumed = True
        return True

    def approve(self, approval_id: uuid.UUID) -> None:
        self.rows[approval_id].status = ApprovalStatus.APPROVED


def registry_with(executor: Executor | None) -> ToolRegistry:
    specs = build_registry().specs()
    if executor is None:
        return ToolRegistry(specs)
    return ToolRegistry(
        replace(s, executor=executor) if s.name == "outbox.send" else s for s in specs
    )


def setup(
    executor: Executor | None = None, workflow_id: str | None = "conv-1"
) -> tuple[ToolGateway, FakeApprovals, FakeRecorder]:
    approvals = FakeApprovals()
    recorder = FakeRecorder()
    ctx = replace(make_ctx(), workflow_id=workflow_id)
    services = ToolServices(engine=None)  # type: ignore[arg-type]
    gateway = ToolGateway(
        registry_with(executor), PolicyEngine(), recorder, services, ctx, approvals
    )
    return gateway, approvals, recorder


async def test_external_write_waits_for_approval_and_reuses_the_pending_one():
    gateway, approvals, recorder = setup()
    first = await gateway.invoke(SEND)
    again = await gateway.invoke(SEND)

    assert first.pending_approval is not None
    assert again.pending_approval == first.pending_approval, "same action, same approval"
    assert len(approvals.rows) == 1
    assert recorder.results == [], "nothing executed"


async def test_changed_args_need_a_new_approval():
    gateway, approvals, _ = setup()
    first = await gateway.invoke(SEND)
    assert first.pending_approval is not None
    approvals.approve(first.pending_approval)

    changed = ToolIntent(tool="outbox.send", args={"recipient": "b@example.com", "body": "hi"})
    result = await gateway.invoke(changed)
    assert result.pending_approval not in (None, first.pending_approval)


async def test_approved_action_runs_once_under_the_original_action_id():
    seen: list[uuid.UUID | None] = []

    async def fake_send(args: Any, ctx: ExecContext, services: ToolServices) -> JsonValue:
        seen.append(ctx.action_id)
        return {"sent": True}

    gateway, approvals, recorder = setup(fake_send)
    pending = await gateway.invoke(SEND)
    assert pending.pending_approval is not None
    original = approvals.rows[pending.pending_approval].action_id
    approvals.approve(pending.pending_approval)

    done = await gateway.invoke(SEND)
    assert done.ok
    assert seen == [original]
    assert [p.action_id for p, _ in recorder.results] == [original]


async def test_without_a_workflow_approval_is_unavailable_and_nothing_runs():
    gateway, approvals, recorder = setup(workflow_id=None)
    result = await gateway.invoke(SEND)
    assert not result.ok and result.pending_approval is None
    assert approvals.rows == {} and recorder.results == []
