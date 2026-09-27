"""Tool boundary types: untrusted ToolIntent in, trusted ActionProposal out."""

import datetime as dt
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

if TYPE_CHECKING:
    from muse.browser.controller import BrowserController
    from muse.modules.artifacts.store import ArtifactStore
    from muse.sandbox.client import SandboxClient

from muse.policy.classification import (
    BrowserContext,
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
    # The workflow that waits on approvals for this run; None outside workflows.
    workflow_id: str | None = None
    approval_ttl_s: int = 7 * 24 * 3600
    # Set by the gateway for the executing action; executors use it as an idempotency key.
    action_id: uuid.UUID | None = None


class ToolResult(BaseModel):
    ok: bool
    output: JsonValue = None
    error: str | None = None
    pending_approval: uuid.UUID | None = None
    deferred: dict[str, str] | None = None


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1


@dataclass(frozen=True)
class ToolServices:
    """Trusted resources executors may use. Never reaches the model."""

    engine: AsyncEngine
    sandbox: "SandboxClient | None" = None
    artifacts: "ArtifactStore | None" = None
    browser: "BrowserController | None" = None


Executor = Callable[[Any, ExecContext, ToolServices], Awaitable[JsonValue]]
Classifier = Callable[[Any, ExecContext, "ToolServices"], Classification]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    classify: Classifier
    executor: Executor = field(repr=False)
    retry: RetryPolicy = RetryPolicy()
    idempotent: bool = False
    timeout_s: int = 60

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
    browser_context: BrowserContext | None = None
    element_name: str | None = None
