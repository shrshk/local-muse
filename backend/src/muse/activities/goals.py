"""Goal activities: activate pending goals, load a goal for a run, record the observation.

Whether to notify is decided here, in trusted code, from structured values — never by the model.
"""

import datetime as dt
import re
import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio import activity

from muse.modules.conversations.conversations_controller import (
    ConversationsController,
    MessagesController,
)
from muse.modules.goals.goal_scheduler import GoalScheduler
from muse.modules.goals.goals_controller import GoalsController
from muse.modules.goals.goals_schema import GoalStatus
from muse.modules.notifications.notification_service import NotificationService
from muse.realtime.publisher import RealtimePublisher, conversation_channel


class ActivateGoalsInput(BaseModel):
    conversation_id: uuid.UUID


class GoalSpec(BaseModel):
    goal_id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    title: str
    objective: str
    condition: str | None
    active: bool


class RecordObservationInput(BaseModel):
    goal_id: uuid.UUID
    value: str
    condition_met: bool | None
    summary: str


class RecordFailureInput(BaseModel):
    goal_id: uuid.UUID
    error: str


class GoalStatusInput(BaseModel):
    goal_id: uuid.UUID
    status: GoalStatus


def normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower().rstrip(".!"))


def importance(goal: dict[str, Any], observation: RecordObservationInput) -> str:
    """High when the user asked for this exact moment; a plain value change is normal."""
    if goal["kind"] == "once" or (goal["condition"] and observation.condition_met):
        return "high"
    return "normal"


def should_notify(goal: dict[str, Any], observation: RecordObservationInput) -> bool:
    if goal["kind"] == "once":
        return True  # "check again tomorrow": the user asked for this one result
    if goal["condition"]:
        return observation.condition_met is True and goal["last_condition"] is not True
    if goal["run_count"] == 0:
        return False  # the first run sets the baseline
    return normalize(observation.value) != normalize(goal["last_value"])


class GoalActivities:
    def __init__(
        self,
        engine: AsyncEngine,
        publisher: RealtimePublisher,
        scheduler: GoalScheduler,
    ) -> None:
        self._engine = engine
        self._publisher = publisher
        self._scheduler = scheduler
        self._notifications = NotificationService(publisher)

    @activity.defn(name="goal.activate_pending")
    async def activate_pending(self, request: ActivateGoalsInput) -> int:
        async with self._engine.begin() as conn:
            claimed = await GoalsController(conn).claim_pending(request.conversation_id)
        for goal in claimed:
            await self._scheduler.activate(goal)
        return len(claimed)

    @activity.defn(name="goal.load")
    async def load(self, goal_id: uuid.UUID) -> GoalSpec | None:
        async with self._engine.connect() as conn:
            row = await GoalsController(conn).get(goal_id)
        if row is None:
            return None
        return GoalSpec(
            goal_id=row["id"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            title=row["title"],
            objective=row["objective"],
            condition=row["condition"],
            active=row["status"] == GoalStatus.ACTIVE.value,
        )

    @activity.defn(name="goal.mark_running")
    async def mark_running(self, goal_id: uuid.UUID) -> None:
        async with self._engine.begin() as conn:
            await GoalsController(conn).set(goal_id, running_since=dt.datetime.now(dt.UTC))

    @activity.defn(name="goal.record")
    async def record(self, request: RecordObservationInput) -> bool:
        now = dt.datetime.now(dt.UTC)
        async with self._engine.begin() as conn:
            goals = GoalsController(conn)
            goal = await goals.get(request.goal_id)
            if goal is None:
                return False
            notify = should_notify(goal, request)
            done = goal["kind"] == "once"
            await goals.set(
                request.goal_id,
                last_value=request.value,
                last_condition=request.condition_met,
                last_summary=request.summary,
                last_run_at=now,
                running_since=None,
                run_count=goal["run_count"] + 1,
                notify_count=goal["notify_count"] + (1 if notify else 0),
                status=GoalStatus.COMPLETED.value if done else goal["status"],
                next_run_at=None
                if done
                else now + dt.timedelta(minutes=goal["every_minutes"] or 0),
            )
            notification = None
            if notify:
                title = f'Goal "{goal["title"]}"'
                notification = await self._notifications.notify(
                    conn,
                    goal["user_id"],
                    "goal",
                    title,
                    request.summary,
                    goal["conversation_id"],
                    request.goal_id,
                    importance=importance(goal, request),
                )
                await ConversationsController(conn).lock(goal["conversation_id"])
                await MessagesController(conn).append(
                    goal["conversation_id"],
                    "event",
                    f"{title}: {request.summary}",
                    uuid.uuid4(),
                )
        if notification is not None:
            await self._notifications.announce(notification, goal["user_id"])
            await self._publisher.publish(
                conversation_channel(goal["conversation_id"]),
                "event.message",
                {"goal_id": str(request.goal_id)},
            )
        return notify

    @activity.defn(name="goal.record_failure")
    async def record_failure(self, request: RecordFailureInput) -> None:
        async with self._engine.begin() as conn:
            await GoalsController(conn).set(
                request.goal_id,
                last_summary=f"The check failed ({request.error}).",
                last_run_at=dt.datetime.now(dt.UTC),
                running_since=None,
            )

    @activity.defn(name="goal.set_status")
    async def set_status(self, request: GoalStatusInput) -> None:
        async with self._engine.begin() as conn:
            await GoalsController(conn).set(request.goal_id, status=request.status.value)
