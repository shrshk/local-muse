"""Model provider interface. Completion and streaming are PydanticAI's `Model` contract."""

from typing import Protocol

from pydantic import BaseModel
from pydantic_ai.models import Model

from muse.modules.health.health_schema import ComponentStatus


class ProviderHealth(BaseModel):
    provider: str
    model: str
    status: ComponentStatus
    detail: str | None = None


class ModelProvider(Protocol):
    name: str
    is_local: bool

    def model(self) -> Model: ...

    async def health(self) -> ProviderHealth: ...
