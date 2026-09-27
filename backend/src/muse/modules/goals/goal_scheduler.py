"""Turns a goal row into Temporal state: a durable timer (once) or a Schedule (recurring).

Workflows are referenced by type name, so the API process never imports workflow code.
"""

import datetime as dt
import uuid

from pydantic import BaseModel
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError, RPCStatusCode

from muse.modules.goals.goals_schema import GoalView


class GoalInput(BaseModel):
    goal_id: uuid.UUID
    fire_at: dt.datetime


class GoalRunInput(BaseModel):
    goal_id: uuid.UUID


def goal_workflow_id(goal_id: uuid.UUID) -> str:
    return f"goal-{goal_id}"


class GoalScheduler:
    def __init__(self, client: Client, task_queue: str) -> None:
        self._client = client
        self._task_queue = task_queue

    async def activate(self, goal: GoalView) -> None:
        if goal.kind == "once":
            assert goal.fire_at is not None
            await self._client.start_workflow(
                "GoalWorkflow",
                GoalInput(goal_id=goal.id, fire_at=goal.fire_at),
                id=goal_workflow_id(goal.id),
                task_queue=self._task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )
            return
        assert goal.every_minutes is not None
        await self._client.create_schedule(
            goal_workflow_id(goal.id),
            Schedule(
                action=ScheduleActionStartWorkflow(
                    "GoalRunWorkflow",
                    GoalRunInput(goal_id=goal.id),
                    id=f"{goal_workflow_id(goal.id)}-run",
                    task_queue=self._task_queue,
                ),
                spec=ScheduleSpec(
                    intervals=[ScheduleIntervalSpec(every=dt.timedelta(minutes=goal.every_minutes))]
                ),
                # A slow check never stacks up behind itself.
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ),
        )

    async def cancel(self, goal: GoalView) -> None:
        try:
            if goal.kind == "once":
                await self._client.get_workflow_handle(goal_workflow_id(goal.id)).cancel()
            else:
                await self._client.get_schedule_handle(goal_workflow_id(goal.id)).delete()
        except RPCError as exc:
            if exc.status is not RPCStatusCode.NOT_FOUND:
                raise
