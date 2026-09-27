"""The gateway's view of approvals. Runs inside tool activities; the workflow owns the wait."""

import json
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from muse.modules.approvals.approvals_controller import (
    ApprovalsController,
    DomainAllowlistController,
    default_expiry,
)
from muse.modules.approvals.approvals_schema import ApprovalStatus
from muse.tools.schema import ActionProposal

SUMMARY_LIMIT = 500


@dataclass(frozen=True)
class OpenApproval:
    id: uuid.UUID
    action_id: uuid.UUID
    status: ApprovalStatus
    consumed: bool
    has_result: bool


class ApprovalStore(Protocol):
    async def open_for(self, approval_key: str, workflow_id: str) -> OpenApproval | None: ...

    async def request(
        self, proposal: ActionProposal, reason: str, workflow_id: str, ttl_seconds: int
    ) -> uuid.UUID: ...

    async def consume(self, approval_id: uuid.UUID) -> bool: ...


def summarize(proposal: ActionProposal, reason: str) -> str:
    target = f" → {proposal.destination}" if proposal.destination else ""
    args = json.dumps(proposal.args, sort_keys=True, ensure_ascii=False)
    return f"{proposal.tool}{target} ({reason}): {args}"[:SUMMARY_LIMIT]


class PostgresApprovalStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def open_for(self, approval_key: str, workflow_id: str) -> OpenApproval | None:
        async with self._engine.connect() as conn:
            row = await ApprovalsController(conn).open_for(approval_key, workflow_id)
        if row is None:
            return None
        return OpenApproval(
            id=row["id"],
            action_id=row["action_id"],
            status=ApprovalStatus(row["status"]),
            consumed=row["consumed_at"] is not None,
            has_result=row["action_result"] is not None,
        )

    async def request(
        self, proposal: ActionProposal, reason: str, workflow_id: str, ttl_seconds: int
    ) -> uuid.UUID:
        async with self._engine.begin() as conn:
            return await ApprovalsController(conn).create(
                action_id=proposal.action_id,
                approval_key=proposal.approval_key,
                user_id=proposal.user_id,
                conversation_id=proposal.conversation_id,
                topic_id=proposal.topic_id,
                workflow_id=workflow_id,
                tool=proposal.tool,
                args=proposal.args,
                destination=proposal.destination,
                summary=summarize(proposal, reason),
                expires_at=default_expiry(ttl_seconds),
            )

    async def consume(self, approval_id: uuid.UUID) -> bool:
        async with self._engine.begin() as conn:
            return await ApprovalsController(conn).consume(approval_id)


class PostgresDomainAllowlist:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def allows(self, user_id: uuid.UUID, domain: str, context: str) -> bool:
        async with self._engine.connect() as conn:
            return await DomainAllowlistController(conn).contains(user_id, domain, context)
