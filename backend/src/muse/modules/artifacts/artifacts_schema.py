"""Shapes for artifacts: files obtained by trusted tools, stored on a worker-only volume."""

import datetime as dt
import uuid

from pydantic import BaseModel

from muse.policy.classification import DataClassification


class ArtifactView(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    topic_id: uuid.UUID | None
    kind: str
    name: str
    size: int
    sha256: str
    classification: DataClassification
    created_at: dt.datetime
