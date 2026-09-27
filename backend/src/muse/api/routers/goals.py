import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from muse.api.deps import current_user, goals_handler, notifications_handler
from muse.modules.auth.auth_schema import Principal
from muse.modules.goals.goals_handler import (
    GoalLimitReached,
    GoalNotFound,
    GoalSchedulingFailed,
    GoalsHandler,
)
from muse.modules.goals.goals_schema import CreateGoal, GoalView
from muse.modules.notifications.notifications_handler import NotificationsHandler
from muse.modules.notifications.notifications_schema import NotificationView

router = APIRouter(tags=["goals"])


@router.post("/api/goals", response_model=GoalView, status_code=status.HTTP_201_CREATED)
async def create_goal(
    body: CreateGoal,
    user: Principal = Depends(current_user),
    handler: GoalsHandler = Depends(goals_handler),
) -> GoalView:
    try:
        return await handler.create(user.id, body)
    except GoalNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found") from exc
    except GoalLimitReached as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"at most {exc} open goals") from exc
    except GoalSchedulingFailed as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "workflow_unavailable") from exc


@router.get("/api/goals", response_model=list[GoalView])
async def list_goals(
    user: Principal = Depends(current_user),
    handler: GoalsHandler = Depends(goals_handler),
) -> list[GoalView]:
    return await handler.list_for_user(user.id)


@router.post("/api/goals/{goal_id}/cancel", response_model=GoalView)
async def cancel_goal(
    goal_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: GoalsHandler = Depends(goals_handler),
) -> GoalView:
    try:
        return await handler.cancel(goal_id, user.id)
    except GoalNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "goal not found") from exc


@router.get("/api/notifications", response_model=list[NotificationView])
async def list_notifications(
    user: Principal = Depends(current_user),
    handler: NotificationsHandler = Depends(notifications_handler),
) -> list[NotificationView]:
    return await handler.list_for_user(user.id)


@router.post("/api/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notification_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: NotificationsHandler = Depends(notifications_handler),
) -> None:
    if not await handler.mark_read(user.id, notification_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
