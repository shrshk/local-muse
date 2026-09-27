"""Agent dependencies: ids only, so Temporal can serialize them into activities."""

import uuid
from dataclasses import dataclass
from typing import Literal

from muse.tools.schema import ExecContext


@dataclass
class AgentDeps:
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    turn_id: uuid.UUID
    topic_id: uuid.UUID | None = None
    actor_id: str = "coordinator"
    trigger: Literal["user", "event"] = "user"

    def exec_context(self) -> ExecContext:
        return ExecContext(
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            topic_id=self.topic_id,
            actor_id=self.actor_id,
            trigger=self.trigger,
        )
