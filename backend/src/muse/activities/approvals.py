"""Approval activities: record a human decision, expire what timed out. Called by workflows."""

import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio import activity

from muse.modules.approvals.approvals_controller import ApprovalsController
from muse.modules.approvals.approvals_schema import ApprovalStatus
from muse.modules.audit.audit_controller import AuditController
from muse.tools.schema import ExecContext


class ApprovalDecisionInput(BaseModel):
    approval_id: uuid.UUID
    approval_key: str
    approved: bool
    decided_by: str
    channel: str


class ExpireApprovalsInput(BaseModel):
    approval_ids: list[uuid.UUID]


class ApprovalActivities:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @activity.defn(name="approval.record_decision")
    async def record_decision(self, decision: ApprovalDecisionInput) -> bool:
        status = ApprovalStatus.APPROVED if decision.approved else ApprovalStatus.DENIED
        async with self._engine.begin() as conn:
            approvals = ApprovalsController(conn)
            applied = await approvals.decide(
                decision.approval_id,
                decision.approval_key,
                status,
                decision.decided_by,
                decision.channel,
            )
            row = await approvals.get_row(decision.approval_id)
            if applied and row is not None:
                ctx = ExecContext(
                    user_id=row["user_id"],
                    conversation_id=row["conversation_id"],
                    topic_id=row["topic_id"],
                    actor_id=f"human:{decision.decided_by}",
                )
                await AuditController(conn).record(
                    "approval.decided",
                    ctx,
                    {
                        "approval_id": str(decision.approval_id),
                        "status": status.value,
                        "channel": decision.channel,
                    },
                    row["action_id"],
                )
        return applied

    @activity.defn(name="approval.expire")
    async def expire(self, request: ExpireApprovalsInput) -> list[uuid.UUID]:
        async with self._engine.begin() as conn:
            return await ApprovalsController(conn).expire(request.approval_ids)
