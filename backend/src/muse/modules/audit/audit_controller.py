"""Append-only audit log."""

import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.shared.tables import audit_events
from muse.tools.schema import ExecContext


class AuditController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def record(
        self,
        event_type: str,
        ctx: ExecContext,
        payload: dict[str, Any],
        action_id: uuid.UUID | None = None,
    ) -> None:
        await self._conn.execute(
            insert(audit_events).values(
                event_type=event_type,
                actor=ctx.actor_id,
                user_id=ctx.user_id,
                conversation_id=ctx.conversation_id,
                action_id=action_id,
                payload=payload,
            )
        )
