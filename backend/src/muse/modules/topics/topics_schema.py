"""Shapes for topics and topic memory."""

import datetime as dt
import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class TopicStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = (TopicStatus.PENDING, TopicStatus.RUNNING)


class TopicView(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    title: str
    objective: str
    status: TopicStatus
    result: JsonValue = None
    created_at: dt.datetime
    finished_at: dt.datetime | None


class TopicMemoryDocument(BaseModel):
    """Spec §15. Never holds secrets or AUTHENTICATED content verbatim."""

    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    objective: str = ""
    decisions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    successful_commands: list[str] = Field(default_factory=list)
    failed_approaches: list[str] = Field(default_factory=list)
    important_artifacts: list[str] = Field(default_factory=list)
    unfinished_work: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class TopicMemoryView(BaseModel):
    topic_id: uuid.UUID
    document: TopicMemoryDocument
    version: int
    updated_at: dt.datetime


class UpdateTopicMemory(BaseModel):
    document: TopicMemoryDocument
    version: int = Field(description="The version you edited; stale versions are rejected")
