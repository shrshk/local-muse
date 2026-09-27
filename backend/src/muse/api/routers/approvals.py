import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from muse.api.deps import approvals_handler, current_user
from muse.modules.approvals.approvals_handler import (
    ApprovalExpired,
    ApprovalMismatch,
    ApprovalNotFound,
    ApprovalsHandler,
    ApprovalWorkflowUnavailable,
)
from muse.modules.approvals.approvals_schema import (
    ApprovalStatus,
    ApprovalView,
    DecisionRequest,
    DecisionResult,
)
from muse.modules.auth.auth_schema import Principal

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")


@router.get("", response_model=list[ApprovalView])
async def list_approvals(
    status_filter: ApprovalStatus | None = Query(default=None, alias="status"),
    user: Principal = Depends(current_user),
    handler: ApprovalsHandler = Depends(approvals_handler),
) -> list[ApprovalView]:
    return await handler.list_for_user(user.id, status_filter)


@router.get("/{approval_id}", response_model=ApprovalView)
async def get_approval(
    approval_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: ApprovalsHandler = Depends(approvals_handler),
) -> ApprovalView:
    try:
        return await handler.get(approval_id, user.id)
    except ApprovalNotFound as exc:
        raise NOT_FOUND from exc


@router.post("/{approval_id}/decision", response_model=DecisionResult)
async def decide(
    approval_id: uuid.UUID,
    body: DecisionRequest,
    user: Principal = Depends(current_user),
    handler: ApprovalsHandler = Depends(approvals_handler),
) -> DecisionResult:
    """A decision on an approval that is no longer pending is a no-op (`changed: false`)."""
    try:
        return await handler.decide(approval_id, user, body)
    except ApprovalNotFound as exc:
        raise NOT_FOUND from exc
    except ApprovalMismatch as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "approval does not match the action's contents"
        ) from exc
    except ApprovalExpired as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "approval expired") from exc
    except ApprovalWorkflowUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "workflow_unavailable") from exc
