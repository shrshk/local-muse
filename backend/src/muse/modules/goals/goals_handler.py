"""Goals created and managed by the owner through the API (the coordinator uses goal.create)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio.service import RPCError

from muse.modules.conversations.conversations_controller import ConversationsController
from muse.modules.goals.goal_scheduler import GoalScheduler
from muse.modules.goals.goals_controller import MAX_ACTIVE_GOALS, GoalsController
from muse.modules.goals.goals_schema import CreateGoal, GoalStatus, GoalView
from muse.shared.logger import get_logger
from muse.shared.settings import Settings
from muse.shared.temporal import TemporalClientProvider

logger = get_logger(__name__)


class GoalNotFound(Exception):
    pass


class GoalLimitReached(Exception):
    pass


class GoalSchedulingFailed(Exception):
    pass


class GoalsHandler:
    def __init__(
        self, engine: AsyncEngine, temporal: TemporalClientProvider, settings: Settings
    ) -> None:
        self._engine = engine
        self._temporal = temporal
        self._task_queue = settings.task_queue_main

    async def _scheduler(self) -> GoalScheduler:
        return GoalScheduler(await self._temporal.get(), self._task_queue)

    async def create(self, user_id: uuid.UUID, body: CreateGoal) -> GoalView:
        async with self._engine.begin() as conn:
            if await ConversationsController(conn).get(body.conversation_id, user_id) is None:
                raise GoalNotFound("conversation")
            goals = GoalsController(conn)
            if await goals.count_open(user_id) >= MAX_ACTIVE_GOALS:
                raise GoalLimitReached(str(MAX_ACTIVE_GOALS))
            goal = await goals.create(user_id, body.conversation_id, body, GoalStatus.ACTIVE)
        try:
            await (await self._scheduler()).activate(goal)
        except RPCError as exc:
            logger.warning("goal_activation_failed", goal_id=str(goal.id), error=exc.status.name)
            async with self._engine.begin() as conn:
                await GoalsController(conn).set(goal.id, status=GoalStatus.CANCELLED.value)
            raise GoalSchedulingFailed(str(goal.id)) from exc
        return goal

    async def list_for_user(self, user_id: uuid.UUID) -> list[GoalView]:
        async with self._engine.connect() as conn:
            return await GoalsController(conn).list_for_user(user_id)

    async def cancel(self, goal_id: uuid.UUID, user_id: uuid.UUID) -> GoalView:
        async with self._engine.begin() as conn:
            goals = GoalsController(conn)
            goal = await goals.get_owned(goal_id, user_id)
            if goal is None:
                raise GoalNotFound(str(goal_id))
            if goal.status in (GoalStatus.PENDING, GoalStatus.ACTIVE):
                await goals.set(goal_id, status=GoalStatus.CANCELLED.value, next_run_at=None)
        if goal.status is GoalStatus.ACTIVE:
            await (await self._scheduler()).cancel(goal)
        async with self._engine.connect() as conn:
            updated = await GoalsController(conn).get_owned(goal_id, user_id)
        assert updated is not None
        return updated
