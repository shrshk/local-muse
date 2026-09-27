"""Shapes for conversations."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from muse.modules.actions.actions_schema import ActionView
from muse.modules.approvals.approvals_schema import ApprovalView
from muse.modules.browser.browser_schema import BrowserSessionView
from muse.modules.topics.topics_schema import TopicView
from muse.workflows.schema import ConversationStatus

Role = Literal["user", "assistant", "event"]


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


class ConversationStateView(BaseModel):
    """Authoritative state for (re)connect. Apply realtime events with seq > `seq`."""

    conversation: ConversationView
    seq: int
    messages: list[MessageView]
    actions: list[ActionView]
    topics: list[TopicView]
    approvals: list[ApprovalView]
    browser_sessions: list[BrowserSessionView]
    status: ConversationStatus
