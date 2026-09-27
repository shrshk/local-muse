"""Tool boundary types: untrusted ToolIntent in, trusted ActionProposal out."""

import datetime as dt
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

from muse.policy.classification import (
    Classification,
    DataClassification,
    RiskClass,
    SideEffectClass,
)


class ToolIntent(BaseModel):
    """Everything the model may say about a tool call. Extra fields are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ExecContext:
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    topic_id: uuid.UUID | None = None
    actor_id: str = "coordinator"
    # What started this run: a user message, or an event (e.g. a topic result being relayed).
    trigger: Literal["user", "event"] = "user"


class ToolResult(BaseModel):
    ok: bool
    output: JsonValue = None
    error: str | None = None


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1


@dataclass(frozen=True)
class ToolServices:
    """Trusted resources executors may use. Never reaches the model."""

    engine: AsyncEngine


Executor = Callable[[Any, ExecContext, ToolServices], Awaitable[JsonValue]]
Classifier = Callable[[Any, ExecContext], Classification]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    classify: Classifier
    executor: Executor = field(repr=False)
    retry: RetryPolicy = RetryPolicy()
    idempotent: bool = False

    @property
    def model_name(self) -> str:
        # OpenAI-style tool names allow only [a-zA-Z0-9_-].
        return self.name.replace(".", "_")


class ActionProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: uuid.UUID
    approval_key: str
    actor_id: str
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    topic_id: uuid.UUID | None
    tool: str
    args: dict[str, JsonValue]
    risk: RiskClass
    side_effect: SideEffectClass
    required_permissions: tuple[str, ...]
    data_classification: DataClassification
    destination: str | None
    credential_ref: str | None
    created_at: dt.datetime
