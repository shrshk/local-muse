"""Queries for approvals and the domain allowlist."""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.approvals.approvals_schema import ApprovalStatus, ApprovalView
from muse.shared.tables import actions, approvals, domain_allowlist

_ACTION_STATUS = {
    ApprovalStatus.APPROVED: "approved",
    ApprovalStatus.DENIED: "denied",
    ApprovalStatus.EXPIRED: "expired",
}


class ApprovalsController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create(self, **values: Any) -> uuid.UUID:
        stmt = insert(approvals).values(status=ApprovalStatus.PENDING.value, **values)
        approval_id: uuid.UUID = (
            await self._conn.execute(stmt.returning(approvals.c.id))
        ).scalar_one()
        return approval_id

    async def open_for(self, approval_key: str, workflow_id: str) -> dict[str, Any] | None:
        """Latest approval for this exact action in this workflow that can still be acted on:
        pending, approved-and-unused, or approved-and-used without a recorded result."""
        stmt = (
            select(approvals, actions.c.result.label("action_result"))
            .join(actions, actions.c.action_id == approvals.c.action_id)
            .where(
                approvals.c.approval_key == approval_key,
                approvals.c.workflow_id == workflow_id,
                or_(
                    approvals.c.status == ApprovalStatus.PENDING.value,
                    and_(
                        approvals.c.status == ApprovalStatus.APPROVED.value,
                        or_(approvals.c.consumed_at.is_(None), actions.c.result.is_(None)),
                    ),
                ),
            )
            .order_by(approvals.c.created_at.desc())
            .limit(1)
        )
        row = (await self._conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def consume(self, approval_id: uuid.UUID) -> bool:
        stmt = (
            update(approvals)
            .where(approvals.c.id == approval_id, approvals.c.consumed_at.is_(None))
            .values(consumed_at=func.now())
        )
        return bool((await self._conn.execute(stmt)).rowcount)

    async def decide(
        self,
        approval_id: uuid.UUID,
        approval_key: str,
        status: ApprovalStatus,
        decided_by: str,
        channel: str,
    ) -> bool:
        """Applies only to a still-pending, unexpired approval with the same key."""
        stmt = (
            update(approvals)
            .where(
                approvals.c.id == approval_id,
                approvals.c.approval_key == approval_key,
                approvals.c.status == ApprovalStatus.PENDING.value,
                approvals.c.expires_at > func.now(),
            )
            .values(
                status=status.value, decided_by=decided_by, channel=channel, decided_at=func.now()
            )
            .returning(approvals.c.action_id)
        )
        action_id = (await self._conn.execute(stmt)).scalar_one_or_none()
        if action_id is None:
            return False
        await self._set_action_status(action_id, status)
        return True

    async def expire(self, approval_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        stmt = (
            update(approvals)
            .where(
                approvals.c.id.in_(approval_ids),
                approvals.c.status == ApprovalStatus.PENDING.value,
            )
            .values(status=ApprovalStatus.EXPIRED.value, decided_at=func.now(), channel="timer")
            .returning(approvals.c.id, approvals.c.action_id)
        )
        rows = (await self._conn.execute(stmt)).all()
        for row in rows:
            await self._set_action_status(row.action_id, ApprovalStatus.EXPIRED)
        return [row.id for row in rows]

    async def get_owned(self, approval_id: uuid.UUID, user_id: uuid.UUID) -> ApprovalView | None:
        stmt = select(approvals).where(
            approvals.c.id == approval_id, approvals.c.user_id == user_id
        )
        row = (await self._conn.execute(stmt)).mappings().first()
        return ApprovalView.model_validate(dict(row)) if row else None

    async def get_row(self, approval_id: uuid.UUID) -> dict[str, Any] | None:
        stmt = select(approvals).where(approvals.c.id == approval_id)
        row = (await self._conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        status: ApprovalStatus | None = None,
        conversation_id: uuid.UUID | None = None,
    ) -> list[ApprovalView]:
        stmt = select(approvals).where(approvals.c.user_id == user_id)
        if status is not None:
            stmt = stmt.where(approvals.c.status == status.value)
        if conversation_id is not None:
            stmt = stmt.where(approvals.c.conversation_id == conversation_id)
        rows = (await self._conn.execute(stmt.order_by(approvals.c.created_at))).mappings().all()
        return [ApprovalView.model_validate(dict(r)) for r in rows]

    async def _set_action_status(self, action_id: uuid.UUID, status: ApprovalStatus) -> None:
        await self._conn.execute(
            update(actions)
            .where(actions.c.action_id == action_id)
            .values(status=_ACTION_STATUS[status])
        )


class DomainAllowlistController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def contains(self, user_id: uuid.UUID, domain: str, context: str) -> bool:
        parts = domain.lower().split(".")
        candidates = [".".join(parts[i:]) for i in range(len(parts) - 1)]  # sub.example.com → …
        stmt = select(func.count()).where(
            domain_allowlist.c.user_id == user_id,
            domain_allowlist.c.context == context,
            domain_allowlist.c.domain.in_(candidates),
        )
        return bool((await self._conn.execute(stmt)).scalar_one())


def default_expiry(ttl_seconds: int) -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(seconds=ttl_seconds)
