"""Phase 6 acceptance: content-bound approvals with a durable wait across a full restart."""

# ruff: noqa: E501  (long lines are SQL and a script executed in the backend container)

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from tests.integration.conftest import (
    WEB_URL,
    async_logged_in_client,
    compose,
    model_online,
    sql,
)

pytestmark = [pytest.mark.integration]
TIMEOUT = 300
CLOCK_THEN_SEND = (
    "First get the current UTC time with the clock tool. Then use the outbox tool to send "
    "alice@example.com the message 'Lunch at noon?'."
)
SEND_ONLY = "Use the outbox tool to send bob@example.com the message 'Running late'."


@pytest.fixture(autouse=True)
def require_model() -> None:
    if not model_online():
        pytest.skip("local model not online")


async def state(client: httpx.AsyncClient, conversation_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/conversations/{conversation_id}/state")).json()
    return body


async def start(client: httpx.AsyncClient, prompt: str) -> str:
    conversation_id: str = (await client.post("/api/conversations", json={})).json()["id"]
    sent = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": prompt}
    )
    assert sent.status_code == 202
    return conversation_id


async def pending_approval(client: httpx.AsyncClient, conversation_id: str) -> dict[str, Any]:
    async with asyncio.timeout(TIMEOUT):
        while True:
            current = await state(client, conversation_id)
            pending = [a for a in current["approvals"] if a["status"] == "PENDING"]
            if pending and current["status"]["waiting_approval_ids"]:
                return pending[0]
            await asyncio.sleep(1)


async def finished_turn(client: httpx.AsyncClient, conversation_id: str) -> dict[str, Any]:
    async with asyncio.timeout(TIMEOUT):
        while True:
            current = await state(client, conversation_id)
            status = current["status"]
            if (
                current["messages"][-1]["role"] == "assistant"
                and not status["running_turn_id"]
                and not status["waiting_approval_ids"]
            ):
                return current
            await asyncio.sleep(1)


async def decide(
    client: httpx.AsyncClient, approval: dict[str, Any], decision: str, key: str | None = None
) -> httpx.Response:
    return await client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": decision, "approval_key": key or approval["approval_key"]},
    )


async def wait_for_stack() -> None:
    async with asyncio.timeout(240), httpx.AsyncClient(base_url=WEB_URL) as anon:
        while True:
            try:
                report = (await anon.get("/api/health")).json()
                if all(c["status"] == "online" for c in report["components"]):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            await asyncio.sleep(3)


def count(query: str) -> int:
    return int(sql(query) or 0)


async def test_approval_survives_a_full_restart_and_is_bound_to_the_exact_action():
    async with async_logged_in_client() as client, async_logged_in_client() as stranger:
        conversation_id = await start(client, CLOCK_THEN_SEND)
        approval = await pending_approval(client, conversation_id)
        assert approval["tool"] == "outbox.send"
        assert approval["args"]["recipient"] == "alice@example.com"
        clock_runs = f"SELECT count(*) FROM actions WHERE conversation_id = '{conversation_id}' AND tool = 'clock.now' AND status = 'executed'"
        assert count(clock_runs) == 1, "the read-only clock call ran without approval"
        assert (
            count(f"SELECT count(*) FROM outbox WHERE conversation_id = '{conversation_id}'") == 0
        )

        # Restart every service; the wait lives in Temporal and Postgres.
        compose("restart")
        await wait_for_stack()
        assert (await pending_approval(client, conversation_id))["id"] == approval["id"]

        changed = await decide(client, approval, "approve", key="0" * 64)
        assert changed.status_code == 409, "approving different contents is rejected"
        forged = await decide(stranger, approval, "approve")
        assert forged.status_code == 404, "another user cannot decide it"
        unknown = await client.post(
            f"/api/approvals/{uuid.uuid4()}/decision",
            json={"decision": "approve", "approval_key": approval["approval_key"]},
        )
        assert unknown.status_code == 404

        first = await decide(client, approval, "approve")
        assert first.status_code == 200 and first.json()["changed"] is True
        second = await decide(client, approval, "approve")
        assert second.status_code == 200 and second.json()["changed"] is False
        assert second.json()["approval"]["status"] == "APPROVED"

        done = await finished_turn(client, conversation_id)

    sent = f"SELECT count(*) FROM outbox WHERE conversation_id = '{conversation_id}'"
    assert count(sent) == 1, "sent exactly once"
    assert_every_send_was_approved(conversation_id)
    assert count(clock_runs) == 1, "resumed without redoing earlier work"
    assert [m["role"] for m in done["messages"]] == ["user", "assistant"]
    outbox_action = next(a for a in done["actions"] if a["tool"] == "outbox.send")
    assert outbox_action["status"] == "executed"
    events = sql(
        "SELECT string_agg(event_type, ',' ORDER BY id) FROM audit_events "
        f"WHERE action_id = '{outbox_action['action_id']}'"
    )
    assert events.split(",")[:3] == ["action.proposed", "action.decided", "approval.requested"]
    assert "approval.decided" in events and events.endswith("action.executed")


async def test_denied_action_never_runs():
    async with async_logged_in_client() as client:
        conversation_id = await start(client, SEND_ONLY)
        approval = await pending_approval(client, conversation_id)
        denied = await decide(client, approval, "deny")
        assert denied.json()["approval"]["status"] == "DENIED"
        done = await finished_turn(client, conversation_id)

    assert count(f"SELECT count(*) FROM outbox WHERE conversation_id = '{conversation_id}'") == 0
    assert next(a for a in done["actions"] if a["tool"] == "outbox.send")["status"] == "denied"


START_WITH_SHORT_EXPIRY = """
import asyncio, uuid
from temporalio.client import WithStartWorkflowOperation
from temporalio.common import WorkflowIDConflictPolicy
from muse.shared.settings import get_settings
from muse.shared.temporal import connect_temporal
from muse.workflows.schema import ConversationState, SendMessageAck, SendMessageInput

async def main():
    client = await connect_temporal(get_settings())
    state = ConversationState(conversation_id=uuid.UUID("{cid}"), user_id=uuid.UUID("{uid}"),
                              history_limit=20, approval_timeout_s=20)
    start = WithStartWorkflowOperation("ConversationWorkflow", state, id="conv-{cid}",
        task_queue="muse-main", id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        result_type=type(None))
    await client.execute_update_with_start_workflow("send_message",
        SendMessageInput(content="{prompt}"), start_workflow_operation=start, result_type=SendMessageAck)

asyncio.run(main())
"""


async def test_unanswered_approval_expires_and_late_decisions_are_no_ops():
    async with async_logged_in_client() as client:
        user_id = (await client.get("/api/auth/me")).json()["id"]
        conversation_id = (await client.post("/api/conversations", json={})).json()["id"]
        script = START_WITH_SHORT_EXPIRY.format(cid=conversation_id, uid=user_id, prompt=SEND_ONLY)
        compose("exec", "-T", "backend", "python", "-c", script)

        approval = await pending_approval(client, conversation_id)
        done = await finished_turn(client, conversation_id)
        expired = next(a for a in done["approvals"] if a["id"] == approval["id"])
        assert expired["status"] == "EXPIRED"
        late = await decide(client, approval, "approve")
        assert late.status_code == 200 and late.json()["changed"] is False

    assert count(f"SELECT count(*) FROM outbox WHERE conversation_id = '{conversation_id}'") == 0
    assert next(a for a in done["actions"] if a["tool"] == "outbox.send")["status"] == "expired"


async def test_a_message_queued_during_a_turn_sees_that_turns_reply():
    """Regression: B is queued (lower seq) before A's reply is saved; B must not redo A.

    Asserts the invariant, not model obedience: whatever the model does with B, A's action is
    never proposed again and nothing is sent without an approval.
    """
    async with async_logged_in_client() as client:
        conversation_id = await start(client, SEND_ONLY)
        first = await pending_approval(client, conversation_id)
        queued = await client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "Now use the outbox tool to send erin@example.com 'Thanks!'."},
        )
        assert queued.status_code == 202
        await decide(client, first, "approve")

        async with asyncio.timeout(TIMEOUT):
            while True:
                current = await state(client, conversation_id)
                for extra in current["approvals"]:
                    if extra["status"] == "PENDING" and extra["id"] != first["id"]:
                        await decide(client, extra, "deny")
                replies = [m for m in current["messages"] if m["role"] == "assistant"]
                if len(replies) >= 2 and not current["status"]["running_turn_id"]:
                    break
                await asyncio.sleep(1)

    bob = [a for a in current["approvals"] if a["args"]["recipient"] == "bob@example.com"]
    assert len(bob) == 1, "the earlier request was proposed again"
    assert_every_send_was_approved(conversation_id)


def assert_every_send_was_approved(conversation_id: str) -> None:
    unapproved = sql(
        "SELECT count(*) FROM outbox o WHERE o.conversation_id = "
        f"'{conversation_id}' AND NOT EXISTS (SELECT 1 FROM approvals a WHERE "
        "a.action_id = o.action_id AND a.status = 'APPROVED')"
    )
    assert int(unapproved) == 0
