"""Payloads that cross the workflow boundary. Ids and small values only; content lives in Postgres
except where an activity must carry it (the prompt, the reply)."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

TURNS_PER_RUN = 50


class PendingTurn(BaseModel):
    turn_id: uuid.UUID
    message_id: uuid.UUID
    seq: int


class ConversationState(BaseModel):
    """Workflow input and the whole Continue-As-New carry-over."""

    conversation_id: uuid.UUID
    user_id: uuid.UUID
    history_limit: int
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
    last_error: str | None = None


class PersistMessageInput(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str


class PersistedMessage(BaseModel):
    id: uuid.UUID
    seq: int


class LoadTurnInput(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    history_limit: int


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class TurnContext(BaseModel):
    prompt: str
    history: list[HistoryItem]


class PublishEventInput(BaseModel):
    channel: str
    event_type: str
    data: dict[str, Any]
