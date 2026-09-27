"""Queries for artifacts and sandbox records."""

import uuid

from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.artifacts.artifacts_schema import ArtifactView
from muse.shared.tables import artifacts, sandboxes


class ArtifactsController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def insert(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        topic_id: uuid.UUID | None,
        kind: str,
        name: str,
        size: int,
        sha256: str,
        classification: str,
    ) -> ArtifactView:
        stmt = (
            insert(artifacts)
            .values(
                user_id=user_id,
                conversation_id=conversation_id,
                topic_id=topic_id,
                kind=kind,
                name=name,
                size=size,
                sha256=sha256,
                classification=classification,
            )
            .returning(artifacts)
        )
        row = (await self._conn.execute(stmt)).mappings().one()
        return ArtifactView.model_validate(dict(row))

    async def get_for_conversation(
        self, artifact_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> ArtifactView | None:
        stmt = select(artifacts).where(
            artifacts.c.id == artifact_id, artifacts.c.conversation_id == conversation_id
        )
        row = (await self._conn.execute(stmt)).mappings().first()
        return ArtifactView.model_validate(dict(row)) if row else None


class SandboxesController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def record(
        self,
        sandbox_id: uuid.UUID,
        conversation_id: uuid.UUID,
        topic_id: uuid.UUID | None,
        volume_name: str,
        status: str,
    ) -> None:
        upsert = pg_insert(sandboxes).values(
            id=sandbox_id,
            conversation_id=conversation_id,
            topic_id=topic_id,
            volume_name=volume_name,
            status=status,
        )
        await self._conn.execute(
            upsert.on_conflict_do_update(
                index_elements=[sandboxes.c.id],
                set_={"status": status, "updated_at": func.now()},
            )
        )
