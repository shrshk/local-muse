"""Human approval decisions (web today; the mobile app later).

Checks here are for the caller; the workflow re-checks through a conditional update, so a race
between two decisions can apply at most one.
"""

import datetime as dt
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio.client import WorkflowUpdateFailedError
from temporalio.service import RPCError

from muse.activities.approvals import ApprovalDecisionInput
from muse.modules.approvals.approvals_controller import ApprovalsController
from muse.modules.approvals.approvals_schema import (
    ApprovalStatus,
    ApprovalView,
    DecisionRequest,
    DecisionResult,
)
from muse.modules.auth.auth_schema import Principal
from muse.shared.logger import get_logger
from muse.shared.temporal import TemporalClientProvider

logger = get_logger(__name__)


class ApprovalNotFound(Exception):
    pass


class ApprovalMismatch(Exception):
    pass


class ApprovalExpired(Exception):
    pass


class ApprovalWorkflowUnavailable(Exception):
    pass


class ApprovalsHandler:
    def __init__(self, engine: AsyncEngine, temporal: TemporalClientProvider) -> None:
        self._engine = engine
        self._temporal = temporal

    async def list_for_user(
        self, user_id: uuid.UUID, status: ApprovalStatus | None
    ) -> list[ApprovalView]:
        async with self._engine.connect() as conn:
            return await ApprovalsController(conn).list_for_user(user_id, status)

    async def get(self, approval_id: uuid.UUID, user_id: uuid.UUID) -> ApprovalView:
        async with self._engine.connect() as conn:
            approval = await ApprovalsController(conn).get_owned(approval_id, user_id)
        if approval is None:
            raise ApprovalNotFound(str(approval_id))
        return approval

    async def decide(
        self,
        approval_id: uuid.UUID,
        user: Principal,
        request: DecisionRequest,
        channel: str = "web",
    ) -> DecisionResult:
        async with self._engine.connect() as conn:
            controller = ApprovalsController(conn)
            approval = await controller.get_owned(approval_id, user.id)
            row = await controller.get_row(approval_id) if approval else None
        if approval is None or row is None:
            raise ApprovalNotFound(str(approval_id))
        if approval.status is not ApprovalStatus.PENDING:
            return DecisionResult(approval=approval, changed=False)
        if request.approval_key != approval.approval_key:
            raise ApprovalMismatch(approval.approval_key)
        if approval.expires_at <= dt.datetime.now(dt.UTC):
            raise ApprovalExpired(str(approval_id))

        decision = ApprovalDecisionInput(
            approval_id=approval_id,
            approval_key=request.approval_key,
            approved=request.decision == "approve",
            decided_by=user.username,
            channel=channel,
        )
        applied = False
        try:
            client = await self._temporal.get()
            applied = await client.get_workflow_handle(row["workflow_id"]).execute_update(
                "decide_approval", decision, result_type=bool
            )
        except WorkflowUpdateFailedError:
            applied = False  # the workflow is not waiting on it (already decided): a no-op
        except RPCError as exc:
            logger.warning(
                "approval_update_failed", approval_id=str(approval_id), error=exc.status.name
            )
            raise ApprovalWorkflowUnavailable(str(approval_id)) from exc
        return DecisionResult(approval=await self.get(approval_id, user.id), changed=applied)
