"""Shapes for goals: delayed or recurring checks that notify when something matters."""

import datetime as dt
import uuid
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

MAX_DELAY_MINUTES = 60 * 24 * 90
MAX_EVERY_MINUTES = 60 * 24 * 30


class GoalStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class GoalTiming(BaseModel):
    """Exactly one of: after_minutes (once), at (once), every_minutes (recurring)."""

    model_config = ConfigDict(extra="forbid")

    after_minutes: int | None = Field(default=None, ge=1, le=MAX_DELAY_MINUTES)
    at: AwareDatetime | None = Field(default=None, description="ISO time with timezone")
    every_minutes: int | None = Field(default=None, ge=1, le=MAX_EVERY_MINUTES)

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        chosen = [v for v in (self.after_minutes, self.at, self.every_minutes) if v is not None]
        if len(chosen) != 1:
            raise ValueError("give exactly one of after_minutes, at, every_minutes")
        return self

    @property
    def kind(self) -> Literal["once", "recurring"]:
        return "recurring" if self.every_minutes else "once"

    def first_run(self, now: dt.datetime) -> dt.datetime:
        if self.at is not None:
            return self.at
        minutes = self.after_minutes or self.every_minutes or 0
        return now + dt.timedelta(minutes=minutes)


class GoalFields(GoalTiming):
    title: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=1, max_length=2000, description="What to check")
    condition: str | None = Field(
        default=None,
        max_length=500,
        description="Notify when this becomes true; without it, notify when the result changes",
    )


class CreateGoal(GoalFields):
    conversation_id: uuid.UUID


class GoalView(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    title: str
    objective: str
    condition: str | None
    kind: str
    fire_at: dt.datetime | None
    every_minutes: int | None
    status: GoalStatus
    last_value: str | None
    last_condition: bool | None
    last_summary: str | None
    last_run_at: dt.datetime | None
    next_run_at: dt.datetime | None
    run_count: int
    notify_count: int
    created_at: dt.datetime
