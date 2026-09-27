"""Phase 4 acceptance: three topics survive a worker restart; cancelling one leaves the others."""

import asyncio
import json
from typing import Any

import httpx
import pytest

from tests.integration.conftest import async_logged_in_client, compose, model_online

pytestmark = [pytest.mark.integration]

CITIES = {"Alpha": "Asia/Tokyo", "Beta": "Europe/London", "Gamma": "America/New_York"}
THREE_TOPICS = (
    "Start exactly three background topics with the topic tool, one call each, and nothing else. "
    + " ".join(
        f"Title '{title}': use the clock tool for {tz}, then write about 120 words on that city."
        for title, tz in CITIES.items()
    )
)
TIMEOUT = 900
FINISHED = {"completed", "failed", "cancelled"}


@pytest.fixture(autouse=True)
def require_model() -> None:
    if not model_online():
        pytest.skip("local model not online")


async def state(client: httpx.AsyncClient, conversation_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/conversations/{conversation_id}/state")).json()
    return body


async def poll(client: httpx.AsyncClient, conversation_id: str, done: Any) -> dict[str, Any]:
    async with asyncio.timeout(TIMEOUT):
        while True:
            current = await state(client, conversation_id)
            if done(current):
                return current
            await asyncio.sleep(2)


def topics_by_title(current: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["title"]: t for t in current["topics"]}


def workflow_status(workflow_id: str) -> str:
    out = compose(
        "exec", "-T", "temporal", "temporal", "workflow", "describe", "-w", workflow_id,
        "--address", "temporal:7233", "-o", "json",
    ).stdout  # fmt: skip
    status: str = json.loads(out)["workflowExecutionInfo"]["status"]
    return status


async def test_three_topics_survive_restart_and_cancelling_one_leaves_the_others():
    async with async_logged_in_client() as client:
        conversation_id = (await client.post("/api/conversations", json={})).json()["id"]
        sent = await client.post(
            f"/api/conversations/{conversation_id}/messages", json={"content": THREE_TOPICS}
        )
        assert sent.status_code == 202

        started = await poll(
            client,
            conversation_id,
            lambda s: sum(t["status"] == "running" for t in s["topics"]) >= 3,
        )
        assert sorted(topics_by_title(started)) == sorted(CITIES), started["topics"]

        compose("kill", "worker", "worker-model")
        await asyncio.sleep(3)
        compose("start", "worker", "worker-model")

        alpha = topics_by_title(started)["Alpha"]
        cancel = await client.post(f"/api/topics/{alpha['id']}/cancel")
        assert cancel.status_code == 202, cancel.text

        finished = await poll(
            client,
            conversation_id,
            lambda s: (
                all(t["status"] in FINISHED for t in s["topics"])
                and not s["status"]["running_turn_id"]
                and not s["status"]["pending_turn_ids"]
            ),
        )
        by_title = topics_by_title(finished)
        assert by_title["Alpha"]["status"] == "cancelled"
        assert by_title["Beta"]["status"] == "completed"
        assert by_title["Gamma"]["status"] == "completed"

        # Cleanup ran: memory records the cancellation; Temporal shows it cancelled, not killed.
        memory = (await client.get(f"/api/topics/{alpha['id']}/memory")).json()
        assert "Cancelled before completion." in memory["document"]["unfinished_work"]
        assert workflow_status(f"topic-{alpha['id']}").endswith("CANCELED")
        assert workflow_status(f"topic-{by_title['Beta']['id']}").endswith("COMPLETED")

        # Results came back to the coordinator: one event per topic, a relay for each completion.
        events = [m["content"] for m in finished["messages"] if m["role"] == "event"]
        assert any('"Alpha" was cancelled' in e for e in events)
        assert sum("completed." in e for e in events) == 2
        assert finished["messages"][-1]["role"] == "assistant"
        # No topic was started by relaying a result.
        assert len(finished["topics"]) == 3


GATEWAY_START_FOUR = """
import asyncio, json, uuid
from muse.policy.engine import PolicyEngine
from muse.shared.db import create_engine
from muse.shared.settings import get_settings
from muse.tools.gateway import ToolGateway
from muse.tools.recorder import PostgresActionRecorder
from muse.tools.schema import ExecContext, ToolIntent, ToolServices
from muse.tools.specs import build_registry

async def main():
    engine = create_engine(get_settings())
    ctx = ExecContext(user_id=uuid.UUID("{uid}"), conversation_id=uuid.UUID("{cid}"))
    gateway = ToolGateway(build_registry(), PolicyEngine(), PostgresActionRecorder(engine),
                          ToolServices(engine=engine), ctx)
    out = []
    for i in range(4):
        args = {{"title": f"t{{i}}", "objective": "o"}}
        r = await gateway.invoke(ToolIntent(tool="topic.start", args=args))
        out.append(r.model_dump(mode="json"))
    print(json.dumps(out))
    await engine.dispose()

asyncio.run(main())
"""


async def test_at_most_three_active_topics_and_pending_ones_cancel_in_place():
    async with async_logged_in_client() as client:
        user_id = (await client.get("/api/auth/me")).json()["id"]
        conversation_id = (await client.post("/api/conversations", json={})).json()["id"]
        script = GATEWAY_START_FOUR.format(uid=user_id, cid=conversation_id)
        stdout = compose("exec", "-T", "worker", "python", "-c", script).stdout
        results = json.loads(stdout.strip().splitlines()[-1])  # earlier lines are gateway logs

        assert [r["ok"] for r in results] == [True, True, True, False]
        assert "at most 3" in results[3]["error"]

        current = await state(client, conversation_id)
        assert [t["status"] for t in current["topics"]] == ["pending"] * 3
        first = current["topics"][0]["id"]
        assert (await client.post(f"/api/topics/{first}/cancel")).json()["status"] == "cancelled"
        again = await client.post(f"/api/topics/{first}/cancel")
        assert again.status_code == 409


async def test_topic_memory_edits_are_version_checked():
    async with async_logged_in_client() as client:
        user_id = (await client.get("/api/auth/me")).json()["id"]
        conversation_id = (await client.post("/api/conversations", json={})).json()["id"]
        script = GATEWAY_START_FOUR.format(uid=user_id, cid=conversation_id)
        compose("exec", "-T", "worker", "python", "-c", script)
        topic_id = (await state(client, conversation_id))["topics"][0]["id"]

        memory = (await client.get(f"/api/topics/{topic_id}/memory")).json()
        document = {**memory["document"], "next_actions": ["check again tomorrow"]}
        saved = await client.put(
            f"/api/topics/{topic_id}/memory",
            json={"document": document, "version": memory["version"]},
        )
        assert saved.status_code == 200
        assert saved.json()["version"] == memory["version"] + 1

        stale = await client.put(
            f"/api/topics/{topic_id}/memory",
            json={"document": document, "version": memory["version"]},
        )
        assert stale.status_code == 409
        rejected = await client.put(
            f"/api/topics/{topic_id}/memory",
            json={"document": {**document, "secret": "x"}, "version": memory["version"] + 1},
        )
        assert rejected.status_code == 422
