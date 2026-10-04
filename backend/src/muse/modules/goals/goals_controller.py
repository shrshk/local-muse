"""Queries for goals."""

import datetime as dt
import uuid
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.goals.goals_schema import GoalFields, GoalStatus, GoalView
from muse.shared.tables import actions, goals

MAX_ACTIVE_GOALS = 20


class GoalsController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        fields: GoalFields,
        status: GoalStatus,
    ) -> GoalView:
        now = dt.datetime.now(dt.UTC)
        stmt = (
            insert(goals)
            .values(
                user_id=user_id,
                conversation_id=conversation_id,
                title=fields.title,
                objective=fields.objective,
                condition=fields.condition,
                kind=fields.kind,
                fire_at=fields.first_run(now) if fields.kind == "once" else None,
                every_minutes=fields.every_minutes,
                status=status.value,
                next_run_at=fields.first_run(now),
            )
            .returning(goals)
        )
        return GoalView.model_validate(dict((await self._conn.execute(stmt)).mappings().one()))

    async def count_open(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            goals.c.user_id == user_id,
            goals.c.status.in_([GoalStatus.PENDING.value, GoalStatus.ACTIVE.value]),
        )
        count: int = (await self._conn.execute(stmt)).scalar_one()
        return count

    async def claim_pending(self, conversation_id: uuid.UUID) -> list[GoalView]:
        stmt = (
            update(goals)
            .where(
                goals.c.conversation_id == conversation_id,
                goals.c.status == GoalStatus.PENDING.value,
            )
            .values(status=GoalStatus.ACTIVE.value, updated_at=func.now())
            .returning(goals)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [GoalView.model_validate(dict(r)) for r in rows]

    async def get(self, goal_id: uuid.UUID) -> dict[str, Any] | None:
        row = (
            (await self._conn.execute(select(goals).where(goals.c.id == goal_id)))
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def get_owned(self, goal_id: uuid.UUID, user_id: uuid.UUID) -> GoalView | None:
        row = await self.get(goal_id)
        return GoalView.model_validate(row) if row and row["user_id"] == user_id else None

    async def list_for_user(self, user_id: uuid.UUID) -> list[GoalView]:
        stmt = select(goals).where(goals.c.user_id == user_id).order_by(goals.c.created_at.desc())
        rows = (await self._conn.execute(stmt)).mappings().all()
        views = [GoalView.model_validate(dict(r)) for r in rows]
        for view in views:
            if view.running_since is not None:
                view.progress_steps, view.progress = await self._progress(
                    view.id, view.running_since
                )
        return views

    async def _progress(self, goal_id: uuid.UUID, since: dt.datetime) -> tuple[int, str | None]:
        """Steps of the running check, from the actions it recorded (tagged with the goal id)."""
        stmt = (
            select(actions.c.tool, actions.c.proposal["args"]["url"].astext.label("url"))
            .where(actions.c.topic_id == goal_id, actions.c.created_at >= since)
            .order_by(actions.c.created_at.desc())
        )
        rows = (await self._conn.execute(stmt)).all()
        if not rows:
            return 0, None
        tool, url = rows[0]
        host = urlsplit(url).hostname if url else None
        return len(rows), f"{tool} {host}" if host else tool

    async def set(self, goal_id: uuid.UUID, **values: Any) -> None:
        await self._conn.execute(
            update(goals).where(goals.c.id == goal_id).values(updated_at=func.now(), **values)
        )
