"""Shapes for the health domain."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ComponentStatus(StrEnum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class ComponentHealth(BaseModel):
    name: str
    status: ComponentStatus
    detail: str | None = None
    latency_ms: float | None = None


class HealthReport(BaseModel):
    status: ComponentStatus
    components: list[ComponentHealth]
    checked_at: dt.datetime


@dataclass(frozen=True)
class HeartbeatRow:
    service: str
    status: str
    detail: dict[str, Any]
    age_seconds: float
