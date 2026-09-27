"""Shapes for approvals: a human decision bound to one action's exact contents."""

import datetime as dt
import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, JsonValue


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class ApprovalView(BaseModel):
    id: uuid.UUID
    action_id: uuid.UUID
    approval_key: str
    conversation_id: uuid.UUID
    topic_id: uuid.UUID | None
    tool: str
    args: dict[str, JsonValue]
    destination: str | None
    summary: str
    status: ApprovalStatus
    decided_by: str | None
    channel: str | None
    decided_at: dt.datetime | None
    expires_at: dt.datetime
    created_at: dt.datetime


class DecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]
    approval_key: str
    """The key of the action the human looked at. A mismatch means the contents changed."""


class DecisionResult(BaseModel):
    approval: ApprovalView
    changed: bool
