"""Policy decisions over trusted ActionProposals. Phase 2 allows everything; Phase 6 adds rules."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from muse.tools.schema import ActionProposal, ExecContext


class DecisionKind(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: DecisionKind
    reason: str | None = None

    @classmethod
    def allow(cls) -> "Decision":
        return cls(kind=DecisionKind.ALLOW)

    @classmethod
    def deny(cls, reason: str) -> "Decision":
        return cls(kind=DecisionKind.DENY, reason=reason)


class PolicyEngine:
    async def evaluate(self, action: ActionProposal, ctx: ExecContext) -> Decision:
        return Decision.allow()
