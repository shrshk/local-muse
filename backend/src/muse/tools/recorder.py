"""Persistence port for the gateway: every proposal, decision, and result is recorded."""

import uuid
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from muse.modules.actions.actions_controller import ActionsController
from muse.modules.audit.audit_controller import AuditController
from muse.policy.engine import Decision
from muse.tools.schema import ActionProposal, ExecContext, ToolResult


class ActionRecorder(Protocol):
    async def audit(
        self,
        event_type: str,
        ctx: ExecContext,
        payload: dict[str, Any],
        action_id: uuid.UUID | None = None,
    ) -> None: ...

    async def record_decision(self, proposal: ActionProposal, decision: Decision) -> None: ...

    async def record_result(self, proposal: ActionProposal, result: ToolResult) -> None: ...


class PostgresActionRecorder:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def audit(
        self,
        event_type: str,
        ctx: ExecContext,
        payload: dict[str, Any],
        action_id: uuid.UUID | None = None,
    ) -> None:
        async with self._engine.begin() as conn:
            await AuditController(conn).record(event_type, ctx, payload, action_id)

    async def record_decision(self, proposal: ActionProposal, decision: Decision) -> None:
        ctx = ExecContext(
            user_id=proposal.user_id,
            conversation_id=proposal.conversation_id,
            topic_id=proposal.topic_id,
            actor_id=proposal.actor_id,
        )
        async with self._engine.begin() as conn:
            await ActionsController(conn).insert(proposal, decision)
            audit = AuditController(conn)
            await audit.record("action.proposed", ctx, {"tool": proposal.tool}, proposal.action_id)
            await audit.record(
                "action.decided",
                ctx,
                {"decision": decision.kind.value, "reason": decision.reason},
                proposal.action_id,
            )

    async def record_result(self, proposal: ActionProposal, result: ToolResult) -> None:
        ctx = ExecContext(
            user_id=proposal.user_id,
            conversation_id=proposal.conversation_id,
            topic_id=proposal.topic_id,
            actor_id=proposal.actor_id,
        )
        event = (
            "action.executed"
            if result.ok
            else ("action.deferred" if result.deferred else "action.failed")
        )
        async with self._engine.begin() as conn:
            await ActionsController(conn).record_result(proposal.action_id, result)
            await AuditController(conn).record(
                event, ctx, {"tool": proposal.tool, "error": result.error}, proposal.action_id
            )
