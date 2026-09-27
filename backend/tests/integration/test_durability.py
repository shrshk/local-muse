"""Phase 3 acceptance: durable turns, streaming, reconnect state, Centrifugo outage, model queue."""

import asyncio
import datetime as dt
import itertools
import json
from typing import Any

import httpx
import pytest

from tests.integration.conftest import async_logged_in_client, compose, model_online
from tests.integration.realtime import ConversationListener

pytestmark = [pytest.mark.integration]

LONG_PROMPT = (
    "Without using any tools, write about 150 words on why durable workflows matter for a "
    "personal assistant."
)
TURN_TIMEOUT = 300


@pytest.fixture(autouse=True)
def require_model() -> None:
    if not model_online():
        pytest.skip("local model not online")


async def new_conversation(client: httpx.AsyncClient) -> str:
    conversation_id: str = (await client.post("/api/conversations", json={})).json()["id"]
    return conversation_id


async def send(client: httpx.AsyncClient, conversation_id: str, content: str) -> dict[str, Any]:
    response = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": content}
    )
    assert response.status_code == 202, response.text
    ack: dict[str, Any] = response.json()
    return ack


async def state(client: httpx.AsyncClient, conversation_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/conversations/{conversation_id}/state")).json()
    return body


async def wait_for_reply(client: httpx.AsyncClient, conversation_id: str) -> dict[str, Any]:
    async with asyncio.timeout(TURN_TIMEOUT):
        while True:
            current = await state(client, conversation_id)
            if any(m["role"] == "assistant" for m in current["messages"]):
                return current
            await asyncio.sleep(1)


async def wait_event(listener: ConversationListener, predicate: Any) -> dict[str, Any]:
    async with asyncio.timeout(TURN_TIMEOUT):
        return await listener.wait_for(predicate)


def is_type(event_type: str, turn_id: str) -> Any:
    return lambda e: e["type"] == event_type and e["data"].get("turn_id") == turn_id


async def test_turn_streams_events_with_gapless_seq_and_state_matches():
    async with async_logged_in_client() as client:
        conversation_id = await new_conversation(client)
        async with ConversationListener(client, conversation_id) as listener:
            ack = await send(client, conversation_id, "What time is it in UTC? Use the clock tool.")
            turn = ack["turn_id"]
            await wait_event(listener, is_type("agent.message", turn))

        types = [e["type"] for e in listener.events]
        assert types[0] == "agent.started"
        assert "agent.token" in types
        assert "tool.started" in types and "tool.completed" in types
        assert types[-1] == "agent.message"
        seqs = [e["seq"] for e in listener.events]
        assert seqs == list(range(seqs[0], seqs[0] + len(seqs))), seqs

        # Reconnect contract: state carries the seq of the last event already reflected in it.
        current = await state(client, conversation_id)
        assert current["seq"] == seqs[-1]
        assert current["messages"][-1]["id"] == listener.events[-1]["data"]["message_id"]
        assert current["status"]["running_turn_id"] is None


async def test_turn_survives_killing_both_workers_mid_response():
    async with async_logged_in_client() as client:
        conversation_id = await new_conversation(client)
        async with ConversationListener(client, conversation_id) as listener:
            ack = await send(client, conversation_id, LONG_PROMPT)
            turn = ack["turn_id"]
            await wait_event(listener, is_type("agent.token", turn))

            compose("kill", "worker", "worker-model")
            await asyncio.sleep(3)
            compose("start", "worker", "worker-model")

            await wait_event(listener, is_type("agent.message", turn))

        attempts = {e["data"]["attempt"] for e in listener.of_type("agent.token")}
        assert max(attempts) >= 2, f"model activity was not retried: {attempts}"

        current = await state(client, conversation_id)
        roles = [m["role"] for m in current["messages"]]
        assert roles == ["user", "assistant"], "exactly one reply, no duplicate or lost message"
        assert len(current["messages"][-1]["content"]) > 200


async def test_centrifugo_outage_does_not_affect_the_turn():
    async with async_logged_in_client() as client:
        conversation_id = await new_conversation(client)
        async with ConversationListener(client, conversation_id) as listener:
            ack = await send(client, conversation_id, LONG_PROMPT)
            await wait_event(listener, is_type("agent.token", ack["turn_id"]))
            last_seen = listener.events[-1]["seq"]
            compose("kill", "centrifugo")
        try:
            current = await wait_for_reply(client, conversation_id)
        finally:
            compose("start", "centrifugo")

        assert [m["role"] for m in current["messages"]] == ["user", "assistant"]
        # Events kept their seq while undeliverable, so a reconnecting client sees the gap.
        assert current["seq"] > last_seen + 1
        assert current["status"]["running_turn_id"] is None


def describe(workflow_id: str) -> dict[str, Any]:
    out = compose(
        "exec", "-T", "temporal", "temporal", "workflow", "describe",
        "-w", workflow_id, "--address", "temporal:7233", "-o", "json",
    ).stdout  # fmt: skip
    described: dict[str, Any] = json.loads(out)
    return described


def parse_time(value: str) -> dt.datetime:
    """Temporal's RFC 3339 times carry nanoseconds; Python keeps microseconds."""
    whole, _, fraction = value.rstrip("Z").partition(".")
    return dt.datetime.fromisoformat(f"{whole}.{(fraction or '0')[:6]:0<6}+00:00")


def model_call_intervals(workflow_id: str) -> list[tuple[dt.datetime, dt.datetime, dt.datetime]]:
    """(scheduled, started, finished) for every model-request attempt, from recorded history."""
    out = compose(
        "exec", "-T", "temporal", "temporal", "workflow", "show", "-w", workflow_id,
        "--address", "temporal:7233", "-o", "json",
    ).stdout  # fmt: skip
    events = json.loads(out)["events"]
    at = {e["eventId"]: parse_time(e["eventTime"]) for e in events}
    model_scheduled = {
        e["eventId"]
        for e in events
        if "model_request"
        in e.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name", "")
    }
    intervals = []
    for e in events:
        for key in ("activityTaskCompletedEventAttributes", "activityTaskFailedEventAttributes"):
            attrs = e.get(key)
            if attrs and attrs["scheduledEventId"] in model_scheduled:
                intervals.append(
                    (at[attrs["scheduledEventId"]], at[attrs["startedEventId"]], at[e["eventId"]])
                )
    return intervals


async def test_model_queue_runs_one_inference_at_a_time():
    async with async_logged_in_client() as client:
        conversations = [await new_conversation(client) for _ in range(2)]
        await asyncio.gather(*(send(client, c, LONG_PROMPT) for c in conversations))
        await asyncio.gather(*(wait_for_reply(client, c) for c in conversations))

    calls = sorted(
        (call for c in conversations for call in model_call_intervals(f"conv-{c}")),
        key=lambda call: call[1],
    )
    assert len(calls) >= 2
    for (_, _, finished), (_, next_started, _) in itertools.pairwise(calls):
        assert next_started >= finished, "two model calls overlapped"
    waited = [started - scheduled for scheduled, started, _ in calls]
    assert max(waited) > dt.timedelta(seconds=2), "a model call queued behind the other"


async def test_turn_survives_an_api_restart():
    async with async_logged_in_client() as client:
        conversation_id = await new_conversation(client)
        await send(client, conversation_id, LONG_PROMPT)
        compose("restart", "backend")
        await wait_for_backend(client)
        current = await wait_for_reply(client, conversation_id)
        assert [m["role"] for m in current["messages"]] == ["user", "assistant"]


async def wait_for_backend(client: httpx.AsyncClient) -> None:
    async with asyncio.timeout(60):
        while True:
            try:
                if (await client.get("/api/health/live")).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)


START_WITH_ONE_TURN_PER_RUN = """
import asyncio, uuid
from temporalio.client import WithStartWorkflowOperation
from temporalio.common import WorkflowIDConflictPolicy
from muse.shared.settings import get_settings
from muse.shared.temporal import connect_temporal
from muse.workflows.schema import ConversationState, SendMessageAck, SendMessageInput

async def main():
    client = await connect_temporal(get_settings())
    state = ConversationState(
        conversation_id=uuid.UUID("{cid}"), user_id=uuid.UUID("{uid}"),
        history_limit=20, turns_per_run=1,
    )
    start = WithStartWorkflowOperation(
        "ConversationWorkflow", state, id="conv-{cid}", task_queue="muse-main",
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING, result_type=type(None),
    )
    await client.execute_update_with_start_workflow(
        "send_message", SendMessageInput(content="Remember the word: tangerine."),
        start_workflow_operation=start, result_type=SendMessageAck,
    )

asyncio.run(main())
"""


async def test_continue_as_new_keeps_the_conversation_going():
    async with async_logged_in_client() as client:
        user_id = (await client.get("/api/auth/me")).json()["id"]
        conversation_id = await new_conversation(client)
        script = START_WITH_ONE_TURN_PER_RUN.format(cid=conversation_id, uid=user_id)
        compose("exec", "-T", "backend", "python", "-c", script)
        await wait_for_reply(client, conversation_id)

        await send(client, conversation_id, "What word did I ask you to remember?")
        async with asyncio.timeout(TURN_TIMEOUT):
            while True:
                current = await state(client, conversation_id)
                if len(current["messages"]) >= 4:
                    break
                await asyncio.sleep(1)

        runs = compose(
            "exec", "-T", "temporal", "temporal", "workflow", "list", "--address",
            "temporal:7233", "--query", f"WorkflowId='conv-{conversation_id}'", "-o", "json",
        ).stdout  # fmt: skip
        statuses = [r["status"] for r in json.loads(runs)]
        assert any("CONTINUED_AS_NEW" in s for s in statuses), statuses
        # History comes from Postgres, not the workflow, so it survives the new run.
        assert "tangerine" in current["messages"][-1]["content"].lower()
