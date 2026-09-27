"""Queries for the actions table."""

import uuid

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.actions.actions_schema import ActionView
from muse.policy.engine import Decision, DecisionKind
from muse.shared.tables import actions
from muse.tools.schema import ActionProposal, ToolResult

_STATUS_BY_DECISION = {
    DecisionKind.ALLOW: "allowed",
    DecisionKind.DENY: "denied",
    DecisionKind.REQUIRE_APPROVAL: "pending_approval",
}


class ActionsController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def insert(self, proposal: ActionProposal, decision: Decision) -> None:
        await self._conn.execute(
            insert(actions).values(
                action_id=proposal.action_id,
                approval_key=proposal.approval_key,
                user_id=proposal.user_id,
                conversation_id=proposal.conversation_id,
                topic_id=proposal.topic_id,
                actor_id=proposal.actor_id,
                tool=proposal.tool,
                proposal=proposal.model_dump(mode="json"),
                decision=decision.kind.value,
                decision_reason=decision.reason,
                status=_STATUS_BY_DECISION[decision.kind],
            )
        )

    async def record_result(self, action_id: uuid.UUID, result: ToolResult) -> None:
        await self._conn.execute(
            update(actions)
            .where(actions.c.action_id == action_id)
            .values(
                status="executed" if result.ok else ("deferred" if result.deferred else "failed"),
                result=result.model_dump(mode="json"),
                executed_at=func.now(),
            )
        )

    async def list_for_conversation(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[ActionView]:
        stmt = (
            select(actions)
            .where(actions.c.conversation_id == conversation_id, actions.c.user_id == user_id)
            .order_by(actions.c.created_at)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [
            ActionView(
                action_id=r["action_id"],
                tool=r["tool"],
                args=r["proposal"]["args"],
                decision=r["decision"],
                status=r["status"],
                result=r["result"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
