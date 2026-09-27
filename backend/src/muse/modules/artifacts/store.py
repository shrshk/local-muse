"""Artifact bytes on a worker-only volume; metadata in Postgres. Never mounted into sandboxes."""

import asyncio
import hashlib
import pathlib
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from muse.modules.artifacts.artifacts_controller import ArtifactsController
from muse.modules.artifacts.artifacts_schema import ArtifactView
from muse.policy.classification import DataClassification


class ArtifactStore:
    def __init__(self, engine: AsyncEngine, root: pathlib.Path) -> None:
        self._engine = engine
        self._root = root

    async def put(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        topic_id: uuid.UUID | None,
        kind: str,
        name: str,
        data: bytes,
        classification: DataClassification,
    ) -> ArtifactView:
        async with self._engine.begin() as conn:
            artifact = await ArtifactsController(conn).insert(
                user_id=user_id,
                conversation_id=conversation_id,
                topic_id=topic_id,
                kind=kind,
                name=name,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                classification=classification.value,
            )
            await asyncio.to_thread(self._write, artifact.id, data)
        return artifact

    async def get(
        self, artifact_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> tuple[ArtifactView, bytes] | None:
        async with self._engine.connect() as conn:
            artifact = await ArtifactsController(conn).get_for_conversation(
                artifact_id, conversation_id
            )
        if artifact is None:
            return None
        return artifact, await asyncio.to_thread(self._path(artifact.id).read_bytes)

    def _path(self, artifact_id: uuid.UUID) -> pathlib.Path:
        return self._root / str(artifact_id)

    def _write(self, artifact_id: uuid.UUID, data: bytes) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._path(artifact_id).write_bytes(data)
