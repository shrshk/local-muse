"""Memory step: profile memory (API + tool + context) and history compaction."""

import asyncio
from typing import Any

import httpx
import pytest

from tests.integration.conftest import async_logged_in_client, compose, model_online, sql

pytestmark = [pytest.mark.integration]
TIMEOUT = 300


async def test_profile_memory_crud_rejects_secrets_and_is_private():
    async with async_logged_in_client() as client, async_logged_in_client() as other:
        saved = await client.put("/api/profile/memory/home_city", json={"value": "Austin"})
        assert saved.status_code == 200
        assert saved.json()["source"] == "user"

        secret = await client.put(
            "/api/profile/memory/openai", json={"value": "sk-proj-abcdefghijklmnopqrstuv"}
        )
        assert secret.status_code == 422
        bad_key = await client.put("/api/profile/memory/Bad Key", json={"value": "x"})
        assert bad_key.status_code == 422

        assert [f["key"] for f in (await client.get("/api/profile/memory")).json()] == ["home_city"]
        assert (await other.get("/api/profile/memory")).json() == []

        assert (await client.delete("/api/profile/memory/home_city")).status_code == 204
        assert (await client.delete("/api/profile/memory/home_city")).status_code == 404


async def send_and_wait(client: httpx.AsyncClient, conversation_id: str, text: str) -> str:
    sent = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": text}
    )
    assert sent.status_code == 202, sent.text
    message_id = sent.json()["message_id"]
    async with asyncio.timeout(TIMEOUT):
        while True:
            state: dict[str, Any] = (
                await client.get(f"/api/conversations/{conversation_id}/state")
            ).json()
            ids = [m["id"] for m in state["messages"]]
            after = state["messages"][ids.index(message_id) + 1 :]
            if (
                any(m["role"] == "assistant" for m in after)
                and not state["status"]["running_turn_id"]
            ):
                reply: str = next(m["content"] for m in after if m["role"] == "assistant")
                return reply
            await asyncio.sleep(1)


async def new_conversation(client: httpx.AsyncClient) -> str:
    conversation_id: str = (await client.post("/api/conversations", json={})).json()["id"]
    return conversation_id


async def test_model_remembers_a_fact_and_uses_it_in_another_conversation():
    if not model_online():
        pytest.skip("local model not online")
    async with async_logged_in_client() as client:
        first = await new_conversation(client)
        await send_and_wait(
            client, first, "Please remember for the future that my home city is Lisbon."
        )
        facts = (await client.get("/api/profile/memory")).json()
        assert any("lisbon" in f["value"].lower() and f["source"] == "agent" for f in facts), facts

        second = await new_conversation(client)
        reply = await send_and_wait(client, second, "Which city do I live in? One word.")
        assert "lisbon" in reply.lower()


START_WITH_TINY_BUDGET = """
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
        history_limit=20, history_token_budget=40,
    )
    start = WithStartWorkflowOperation(
        "ConversationWorkflow", state, id="conv-{cid}", task_queue="muse-main",
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING, result_type=type(None),
    )
    await client.execute_update_with_start_workflow(
        "send_message",
        SendMessageInput(content="For our trip we picked Porto as the destination. Just say ok."),
        start_workflow_operation=start, result_type=SendMessageAck,
    )

asyncio.run(main())
"""


async def test_old_turns_are_compacted_and_still_recalled():
    if not model_online():
        pytest.skip("local model not online")
    async with async_logged_in_client() as client:
        user_id = (await client.get("/api/auth/me")).json()["id"]
        conversation_id = await new_conversation(client)
        compose(
            "exec", "-T", "backend", "python", "-c",
            START_WITH_TINY_BUDGET.format(cid=conversation_id, uid=user_id),
        )  # fmt: skip
        await send_and_wait(client, conversation_id, "Name one color of the sky. One word.")
        await send_and_wait(client, conversation_id, "Name one fruit that is yellow. One word.")

        # Compaction runs after the reply is saved; give it time to finish.
        async with asyncio.timeout(TIMEOUT):
            while True:
                summary = latest_summary(conversation_id)
                if summary:
                    break
                await asyncio.sleep(2)
        assert "porto" in summary.lower(), summary

        reply = await send_and_wait(
            client, conversation_id, "Which destination did we pick for the trip? One word."
        )
        assert "porto" in reply.lower()


def latest_summary(conversation_id: str) -> str:
    return sql(
        "SELECT content FROM conversation_summaries "
        f"WHERE conversation_id = '{conversation_id}' ORDER BY up_to_seq DESC LIMIT 1"
    )
