"""goal.create: a delayed or recurring check. Recorded here; trusted code activates it."""

from pydantic import JsonValue

from muse.modules.conversations.conversations_controller import ConversationsController
from muse.modules.goals.goals_controller import MAX_ACTIVE_GOALS, GoalsController
from muse.modules.goals.goals_schema import GoalFields, GoalStatus
from muse.tools.errors import ToolExecutionError
from muse.tools.schema import ExecContext, ToolServices


class GoalCreateArgs(GoalFields):
    """title, objective, optional condition, and exactly one of after_minutes/at/every_minutes."""


async def create(args: GoalCreateArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    if ctx.topic_id is not None:
        raise ToolExecutionError("background work cannot schedule goals")
    if ctx.trigger != "user":
        raise ToolExecutionError("goals can only be created in reply to a user message")
    async with services.engine.begin() as conn:
        await ConversationsController(conn).lock(ctx.conversation_id)
        goals = GoalsController(conn)
        if await goals.count_open(ctx.user_id) >= MAX_ACTIVE_GOALS:
            raise ToolExecutionError(f"at most {MAX_ACTIVE_GOALS} goals can be open at once")
        goal = await goals.create(ctx.user_id, ctx.conversation_id, args, GoalStatus.PENDING)
    return {
        "goal_id": str(goal.id),
        "title": goal.title,
        "kind": goal.kind,
        "first_run": goal.next_run_at.isoformat() if goal.next_run_at else None,
    }
