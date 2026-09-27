"""Sandbox cleanup: destroy the container, keep the workspace volume (spec §10.3)."""

import uuid

from pydantic import BaseModel
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio import activity

from muse.sandbox.client import SandboxClient
from muse.shared.tables import sandboxes


class ReleaseSandboxInput(BaseModel):
    sandbox_id: uuid.UUID


class SandboxActivities:
    def __init__(self, engine: AsyncEngine, client: SandboxClient) -> None:
        self._engine = engine
        self._client = client

    @activity.defn(name="sandbox.release")
    async def release(self, request: ReleaseSandboxInput) -> None:
        await self._client.destroy(request.sandbox_id)
        async with self._engine.begin() as conn:
            await conn.execute(
                update(sandboxes)
                .where(sandboxes.c.id == request.sandbox_id)
                .values(status="stopped", updated_at=func.now())
            )
