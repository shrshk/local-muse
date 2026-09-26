"""Shapes for recorded actions."""

import datetime as dt
import uuid

from pydantic import BaseModel, JsonValue


class ActionView(BaseModel):
    action_id: uuid.UUID
    tool: str
    args: dict[str, JsonValue]
    decision: str
    status: str
    result: JsonValue
    created_at: dt.datetime
