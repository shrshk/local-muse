"""In-memory test doubles."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from muse.policy.engine import Decision
from muse.tools.schema import ActionProposal, ExecContext, ToolResult


@dataclass
class FakeRecorder:
    events: list[tuple[str, dict[str, Any], uuid.UUID | None]] = field(default_factory=list)
    decisions: list[tuple[ActionProposal, Decision]] = field(default_factory=list)
    results: list[tuple[ActionProposal, ToolResult]] = field(default_factory=list)

    async def audit(
        self,
        event_type: str,
        ctx: ExecContext,
        payload: dict[str, Any],
        action_id: uuid.UUID | None = None,
    ) -> None:
        self.events.append((event_type, payload, action_id))

    async def record_decision(self, proposal: ActionProposal, decision: Decision) -> None:
        self.decisions.append((proposal, decision))
        self.events.append(
            ("action.decided", {"decision": decision.kind.value}, proposal.action_id)
        )

    async def record_result(self, proposal: ActionProposal, result: ToolResult) -> None:
        self.results.append((proposal, result))

    def event_types(self) -> list[str]:
        return [e[0] for e in self.events]


def make_ctx() -> ExecContext:
    return ExecContext(user_id=uuid.uuid4(), conversation_id=uuid.uuid4())
