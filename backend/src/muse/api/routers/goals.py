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
from muse.modules.notifications.budget import Preference
from muse.modules.notifications.notifications_handler import (
    NotificationNotFound,
    NotificationsHandler,
    NotTunable,
)
from muse.modules.notifications.notifications_schema import NotificationView
from muse.modules.push.push_schema import FeedbackRequest, PreferenceUpdate

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


@router.get("/api/notifications/{notification_id}", response_model=NotificationView)
async def get_notification(
    notification_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: NotificationsHandler = Depends(notifications_handler),
) -> NotificationView:
    """The service worker reads the text here; the push itself carried only the id."""
    try:
        return await handler.get(user.id, notification_id)
    except NotificationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found") from exc


@router.post("/api/notifications/{notification_id}/feedback", response_model=Preference)
async def notification_feedback(
    notification_id: uuid.UUID,
    body: FeedbackRequest,
    user: Principal = Depends(current_user),
    handler: NotificationsHandler = Depends(notifications_handler),
) -> Preference:
    try:
        return await handler.feedback(user.id, notification_id, body.signal)
    except NotificationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found") from exc
    except NotTunable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "this kind always notifies") from exc


@router.get("/api/notification_preferences", response_model=list[Preference])
async def list_preferences(
    user: Principal = Depends(current_user),
    handler: NotificationsHandler = Depends(notifications_handler),
) -> list[Preference]:
    return await handler.preferences(user.id)


@router.put("/api/notification_preferences/{kind}", response_model=Preference)
async def set_preference(
    kind: str,
    body: PreferenceUpdate,
    user: Principal = Depends(current_user),
    handler: NotificationsHandler = Depends(notifications_handler),
) -> Preference:
    if not kind.isidentifier() or len(kind) > 40:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid kind")
    try:
        return await handler.set_preference(user.id, kind, body.level, body.daily_cap)
    except NotTunable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "this kind always notifies") from exc
