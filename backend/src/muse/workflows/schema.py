"""Payloads that cross the workflow boundary. Ids and small values only; content lives in Postgres
except where an activity must carry it (the prompt, the reply)."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

TURNS_PER_RUN = 50
APPROVAL_TIMEOUT_S = 7 * 24 * 3600


class PendingTurn(BaseModel):
    """A queued unit of coordinator work: a user message, or a topic result to relay."""

    turn_id: uuid.UUID
    message_id: uuid.UUID
    seq: int
    kind: Literal["user", "topic_result"] = "user"


class ConversationState(BaseModel):
    """Workflow input and the whole Continue-As-New carry-over."""

    conversation_id: uuid.UUID
    user_id: uuid.UUID
    history_limit: int
    history_token_budget: int = 8000
    approval_timeout_s: int = APPROVAL_TIMEOUT_S
    turns_per_run: int = TURNS_PER_RUN
    pending: list[PendingTurn] = Field(default_factory=list)


class SendMessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class SendMessageAck(BaseModel):
    message_id: uuid.UUID
    seq: int
    turn_id: uuid.UUID


class ConversationStatus(BaseModel):
    running_turn_id: uuid.UUID | None = None
    pending_turn_ids: list[uuid.UUID] = Field(default_factory=list)
    active_topic_ids: list[uuid.UUID] = Field(default_factory=list)
    waiting_approval_ids: list[uuid.UUID] = Field(default_factory=list)
    browser_modes: dict[str, str] = Field(default_factory=dict)
    last_error: str | None = None


class PersistMessageInput(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["user", "assistant", "event"]
    content: str


class PersistedMessage(BaseModel):
    id: uuid.UUID
    seq: int


class LoadTurnInput(BaseModel):
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    message_id: uuid.UUID
    history_limit: int
    token_budget: int


class HistoryItem(BaseModel):
    role: Literal["user", "assistant", "event"]
    content: str


class TurnContext(BaseModel):
    prompt: str
    history: list[HistoryItem]
    context: str | None = None
    compact_up_to: int | None = None


class CompactionInput(BaseModel):
    conversation_id: uuid.UUID
    up_to_seq: int
    max_chars: int


class CompactionSource(BaseModel):
    previous_summary: str | None
    transcript: str


class SaveSummaryInput(BaseModel):
    conversation_id: uuid.UUID
    up_to_seq: int
    content: str


class ProfileContextInput(BaseModel):
    user_id: uuid.UUID


class PublishEventInput(BaseModel):
    channel: str
    event_type: str
    data: dict[str, Any]


class ClaimTopicsInput(BaseModel):
    conversation_id: uuid.UUID


class TopicStart(BaseModel):
    topic_id: uuid.UUID
    title: str
    objective: str


class TopicInput(BaseModel):
    topic_id: uuid.UUID
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    title: str
    objective: str
    step_limit: int
    approval_timeout_s: int = APPROVAL_TIMEOUT_S


class TopicResult(BaseModel):
    topic_id: uuid.UUID
    title: str
    status: Literal["completed", "failed", "cancelled"]
    summary: str | None = None
    error: str | None = None


class FinishTopicInput(BaseModel):
    topic_id: uuid.UUID
    status: Literal["completed", "failed", "cancelled"]
    report: dict[str, Any] | None = None
    error: str | None = None
