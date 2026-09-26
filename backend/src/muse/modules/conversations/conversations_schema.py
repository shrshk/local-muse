"""Shapes for conversations and chat turns."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

Role = Literal["user", "assistant"]


class ConversationView(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class MessageView(BaseModel):
    id: uuid.UUID
    role: Role
    content: str
    seq: int
    created_at: dt.datetime


class CreateConversation(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class SendMessage(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class ToolCallView(BaseModel):
    action_id: uuid.UUID
    tool: str
    args: dict[str, JsonValue]
    decision: str
    ok: bool
    output: JsonValue = None
    error: str | None = None


class TurnResult(BaseModel):
    user_message: MessageView
    assistant_message: MessageView
    tool_calls: list[ToolCallView]
