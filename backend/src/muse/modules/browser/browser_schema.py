"""Shapes for browser sessions, human takeover and the domain allowlist."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field

BrowserMode = Literal["agent", "human"]


class BrowserSessionView(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    topic_id: uuid.UUID | None
    context: str
    mode: BrowserMode
    current_url: str | None
    status: str
    frame_version: int
    updated_at: dt.datetime


class SetModeRequest(BaseModel):
    mode: BrowserMode


class HumanInput(BaseModel):
    """What a human can do while in control. Coordinates are in page viewport pixels."""

    kind: Literal["click", "type", "press", "scroll", "navigate"]
    x: int | None = Field(default=None, ge=0, le=4000)
    y: int | None = Field(default=None, ge=0, le=4000)
    text: str | None = Field(default=None, max_length=2000)
    key: str | None = Field(default=None, max_length=40)
    url: str | None = Field(default=None, max_length=2000)
    direction: Literal["up", "down"] | None = None


class AllowlistEntry(BaseModel):
    domain: str
    context: str
    created_at: dt.datetime


class PutAllowlistEntry(BaseModel):
    domain: str = Field(
        pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
    )
