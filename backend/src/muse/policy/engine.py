"""Policy decisions over trusted ActionProposals (spec §7). Rules are ordered; first match wins.

Unknown tools never reach this module: the gateway denies them before a proposal exists.
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from muse.policy.classification import DataClassification, RiskClass, SideEffectClass
from muse.tools.schema import ActionProposal, ExecContext


class DecisionKind(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: DecisionKind
    reason: str | None = None
    rule: str | None = None

    @classmethod
    def allow(cls, rule: str | None = None) -> "Decision":
        return cls(kind=DecisionKind.ALLOW, rule=rule)

    @classmethod
    def deny(cls, reason: str, rule: str | None = None) -> "Decision":
        return cls(kind=DecisionKind.DENY, reason=reason, rule=rule)

    @classmethod
    def require_approval(cls, reason: str, rule: str | None = None) -> "Decision":
        return cls(kind=DecisionKind.REQUIRE_APPROVAL, reason=reason, rule=rule)


class DomainAllowlist(Protocol):
    async def allows(self, user_id: uuid.UUID, domain: str, context: str) -> bool: ...


class EmptyAllowlist:
    async def allows(self, user_id: uuid.UUID, domain: str, context: str) -> bool:
        return False


# Documented as incomplete: a pattern list, not an understanding of intent.
ESCALATION = re.compile(r"buy|purchase|order|confirm|send|submit|pay|delete|remove|transfer", re.I)
BROWSER_READS = {"browser.navigate", "browser.snapshot", "browser.screenshot", "browser.scroll"}
BROWSER_MUTATIONS = {"browser.click", "browser.fill", "browser.press", "browser.download"}
LOCAL_ASSISTANT_TOOLS = {"clock.now", "profile.remember", "topic.start"}
APPROVAL_SIDE_EFFECTS = {
    SideEffectClass.MESSAGE_SEND,
    SideEffectClass.REMOTE_UPDATE,
    SideEffectClass.PURCHASE,
    SideEffectClass.DELETE,
}
APPROVAL_RISKS = {
    RiskClass.EXTERNAL_WRITE,
    RiskClass.SENSITIVE_EXTERNAL_WRITE,
    RiskClass.DESTRUCTIVE,
}

RuleFn = Callable[[ActionProposal, ExecContext, DomainAllowlist], Awaitable[Decision | None]]


@dataclass(frozen=True)
class Rule:
    name: str
    check: RuleFn


def _escalates(action: ActionProposal) -> bool:
    return bool(action.element_name and ESCALATION.search(action.element_name))


async def _secret(a: ActionProposal, c: ExecContext, al: DomainAllowlist) -> Decision | None:
    if a.data_classification is DataClassification.SECRET:
        return Decision.deny("secret data never leaves", "secret")
    return None


async def _sandbox(a: ActionProposal, c: ExecContext, al: DomainAllowlist) -> Decision | None:
    return Decision.allow("sandbox") if a.tool.startswith("sandbox.") else None


async def _browser(a: ActionProposal, c: ExecContext, al: DomainAllowlist) -> Decision | None:
    if not a.tool.startswith("browser."):
        return None
    if a.tool == "browser.open_session" and a.browser_context == "authenticated":
        return Decision.require_approval("opening a logged-in browser session", "browser_auth_open")
    if a.tool in BROWSER_READS or a.tool in {"browser.open_session", "browser.close_session"}:
        return Decision.allow("browser_read")
    if a.tool in BROWSER_MUTATIONS:
        if a.browser_context == "authenticated":
            return Decision.require_approval("changing a logged-in page", "browser_auth_mutation")
        if _escalates(a):
            return Decision.require_approval(
                f"element looks consequential: {a.element_name!r}", "browser_escalation"
            )
        if a.destination and await al.allows(a.user_id, a.destination, "research"):
            return Decision.allow("browser_allowlisted")
        return Decision.require_approval(
            f"interacting with {a.destination or 'an unknown site'}", "browser_not_allowlisted"
        )
    return None


async def _named_allows(a: ActionProposal, c: ExecContext, al: DomainAllowlist) -> Decision | None:
    if a.tool in {"http.get", "web.search", "notify.user"}:
        return Decision.allow("public_read_or_owner_notify")
    if a.tool in LOCAL_ASSISTANT_TOOLS:
        return Decision.allow("local_assistant")
    return None


async def _approval_classes(
    a: ActionProposal, c: ExecContext, al: DomainAllowlist
) -> Decision | None:
    if a.side_effect in APPROVAL_SIDE_EFFECTS:
        return Decision.require_approval(f"side effect {a.side_effect.value}", "side_effect")
    if a.risk in APPROVAL_RISKS:
        return Decision.require_approval(f"risk {a.risk.value}", "risk")
    return None


async def _read_only(a: ActionProposal, c: ExecContext, al: DomainAllowlist) -> Decision | None:
    if a.risk is RiskClass.READ_ONLY and a.side_effect in {
        SideEffectClass.NONE,
        SideEffectClass.NETWORK_READ,
    }:
        return Decision.allow("read_only")
    return None


RULES: tuple[Rule, ...] = (
    Rule("secret", _secret),
    Rule("sandbox", _sandbox),
    Rule("browser", _browser),
    Rule("named_allows", _named_allows),
    Rule("approval_classes", _approval_classes),
    Rule("read_only", _read_only),
)


class PolicyEngine:
    def __init__(self, allowlist: DomainAllowlist | None = None) -> None:
        self._allowlist: DomainAllowlist = allowlist or EmptyAllowlist()

    async def evaluate(self, action: ActionProposal, ctx: ExecContext) -> Decision:
        for rule in RULES:
            decision = await rule.check(action, ctx, self._allowlist)
            if decision is not None:
                return decision
        return Decision.require_approval("no rule allows this action", "default")
