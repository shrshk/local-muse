"""Shapes for profile memory."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

KEY_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,63}$"


class ProfileFact(BaseModel):
    key: str
    value: str
    source: Literal["user", "agent"]
    updated_at: dt.datetime


class PutProfileFact(BaseModel):
    value: str = Field(min_length=1, max_length=500)
