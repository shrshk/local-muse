"""Shapes for notifications: things that deserve the user's attention."""

import datetime as dt
import uuid

from pydantic import BaseModel


class NotificationView(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None
    goal_id: uuid.UUID | None
    kind: str
    importance: str = "normal"
    approval_id: uuid.UUID | None = None
    title: str
    body: str
    created_at: dt.datetime
    read_at: dt.datetime | None
