"""The §7 rule table, row by row."""

import datetime as dt
import uuid
from typing import Any

import pytest

from muse.policy.classification import DataClassification, RiskClass, SideEffectClass
from muse.policy.engine import DecisionKind, PolicyEngine
from muse.tools.schema import ActionProposal
from tests.fakes import make_ctx

ALLOW, DENY, APPROVE = DecisionKind.ALLOW, DecisionKind.DENY, DecisionKind.REQUIRE_APPROVAL


class Allowlist:
    def __init__(self, *domains: str) -> None:
        self.domains = set(domains)

    async def allows(self, user_id: uuid.UUID, domain: str, context: str) -> bool:
        return context == "research" and domain in self.domains


def proposal(tool: str, **overrides: Any) -> ActionProposal:
    base: dict[str, Any] = {
        "action_id": uuid.uuid4(),
        "approval_key": "k",
        "actor_id": "coordinator",
        "user_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "topic_id": None,
        "tool": tool,
        "args": {},
        "risk": RiskClass.READ_ONLY,
        "side_effect": SideEffectClass.NONE,
        "required_permissions": (),
        "data_classification": DataClassification.PUBLIC,
        "destination": None,
        "credential_ref": None,
        "created_at": dt.datetime.now(dt.UTC),
    }
    return ActionProposal(**{**base, **overrides})


CASES = [
    (
        "secret data is denied",
        proposal("clock.now", data_classification=DataClassification.SECRET),
        DENY,
    ),
    (
        "sandbox exec allowed",
        proposal(
            "sandbox.exec",
            risk=RiskClass.LOCAL_MUTATION,
            side_effect=SideEffectClass.LOCAL_FILE_WRITE,
        ),
        ALLOW,
    ),
    ("research snapshot allowed", proposal("browser.snapshot", browser_context="research"), ALLOW),
    (
        "research click, allowlisted",
        proposal(
            "browser.click",
            browser_context="research",
            destination="docs.python.org",
            element_name="Next",
        ),
        ALLOW,
    ),
    (
        "research click, not allowlisted",
        proposal(
            "browser.click",
            browser_context="research",
            destination="shop.example",
            element_name="Next",
        ),
        APPROVE,
    ),
    (
        "research click on 'Buy now' escalates even if allowlisted",
        proposal(
            "browser.click",
            browser_context="research",
            destination="docs.python.org",
            element_name="Buy now",
        ),
        APPROVE,
    ),
    (
        "open authenticated session",
        proposal("browser.open_session", browser_context="authenticated"),
        APPROVE,
    ),
    (
        "authenticated fill",
        proposal("browser.fill", browser_context="authenticated", destination="mail.example"),
        APPROVE,
    ),
    (
        "authenticated snapshot allowed",
        proposal("browser.snapshot", browser_context="authenticated"),
        ALLOW,
    ),
    ("http.get allowed", proposal("http.get", side_effect=SideEffectClass.NETWORK_READ), ALLOW),
    ("web.search allowed", proposal("web.search", side_effect=SideEffectClass.NETWORK_READ), ALLOW),
    (
        "notify.user allowed",
        proposal("notify.user", side_effect=SideEffectClass.MESSAGE_SEND),
        ALLOW,
    ),
    ("local assistant tool allowed", proposal("topic.start", risk=RiskClass.LOCAL_MUTATION), ALLOW),
    (
        "message send needs approval",
        proposal(
            "outbox.send", risk=RiskClass.EXTERNAL_WRITE, side_effect=SideEffectClass.MESSAGE_SEND
        ),
        APPROVE,
    ),
    (
        "purchase needs approval",
        proposal("shop.buy", side_effect=SideEffectClass.PURCHASE),
        APPROVE,
    ),
    ("destructive needs approval", proposal("files.wipe", risk=RiskClass.DESTRUCTIVE), APPROVE),
    (
        "unknown read-only allowed",
        proposal("weather.get", side_effect=SideEffectClass.NETWORK_READ),
        ALLOW,
    ),
    (
        "unknown local mutation defaults to approval",
        proposal("calendar.edit", risk=RiskClass.LOCAL_MUTATION),
        APPROVE,
    ),
]


@pytest.mark.parametrize(("name", "action", "expected"), CASES, ids=[c[0] for c in CASES])
async def test_rule_table(name: str, action: ActionProposal, expected: DecisionKind):
    decision = await PolicyEngine(Allowlist("docs.python.org")).evaluate(action, make_ctx())
    assert decision.kind is expected, decision
