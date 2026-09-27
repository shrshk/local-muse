"""Phase 9 acceptance: durable timers across a full restart; recurring goals notify on change."""

import asyncio
import datetime as dt
import json
from typing import Any

import httpx
import pytest

from tests.integration.conftest import async_logged_in_client, compose, model_online
from tests.integration.test_approvals import wait_for_stack

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def require_model() -> None:
    if not model_online():
        pytest.skip("local model not online")


async def conversation(client: httpx.AsyncClient) -> str:
    conversation_id: str = (await client.post("/api/conversations", json={})).json()["id"]
    return conversation_id


async def goal(client: httpx.AsyncClient, goal_id: str) -> dict[str, Any]:
    goals: list[dict[str, Any]] = (await client.get("/api/goals")).json()
    return next(g for g in goals if g["id"] == goal_id)


async def until(
    client: httpx.AsyncClient, goal_id: str, done: Any, limit_s: float
) -> dict[str, Any]:
    async with asyncio.timeout(limit_s):
        while True:
            current = await goal(client, goal_id)
            if done(current):
                return current
            await asyncio.sleep(3)


def describe(kind: str, name: str) -> dict[str, Any]:
    out = compose(
        "exec", "-T", "temporal", "temporal", kind, "describe",
        *(("-w", name) if kind == "workflow" else ("-s", name)),
        "--address", "temporal:7233", "-o", "json", check=False,
    )  # fmt: skip
    return json.loads(out.stdout) if out.returncode == 0 else {}


async def test_a_one_shot_goal_fires_on_time_after_a_full_restart():
    async with async_logged_in_client() as client:
        cid = await conversation(client)
        created = await client.post(
            "/api/goals",
            json={
                "conversation_id": cid,
                "title": "UTC hour",
                "objective": "Use the clock tool and report the current UTC hour as a number.",
                "after_minutes": 2,
            },
        )
        assert created.status_code == 201
        g = created.json()
        fire_at = dt.datetime.fromisoformat(g["fire_at"])

        compose("restart")  # every service, while the timer is pending
        await wait_for_stack()

        done = await until(client, g["id"], lambda x: x["status"] == "completed", 600)
        ran_at = dt.datetime.fromisoformat(done["last_run_at"])
        assert fire_at <= ran_at <= fire_at + dt.timedelta(minutes=5), (fire_at, ran_at)
        assert done["notify_count"] == 1
        notes = (await client.get("/api/notifications")).json()
        assert any(n["goal_id"] == g["id"] for n in notes)
        events = (await client.get(f"/api/conversations/{cid}/state")).json()["messages"]
        assert any(m["role"] == "event" and "UTC hour" in m["content"] for m in events)


async def test_check_again_tomorrow_sleeps_on_a_durable_timer():
    async with async_logged_in_client() as client:
        cid = await conversation(client)
        await client.post(
            f"/api/conversations/{cid}/messages",
            json={
                "content": "Check the heading of https://example.com again tomorrow and tell me."
            },
        )
        async with asyncio.timeout(300):
            while True:
                goals = [
                    g
                    for g in (await client.get("/api/goals")).json()
                    if g["conversation_id"] == cid
                ]
                if goals and goals[0]["status"] == "active":
                    break
                await asyncio.sleep(2)
        g = goals[0]
        next_run = dt.datetime.fromisoformat(g["next_run_at"])
        now = dt.datetime.now(dt.UTC)
        assert g["kind"] == "once"
        assert dt.timedelta(hours=6) < next_run - now < dt.timedelta(hours=48), next_run
        info = describe("workflow", f"goal-{g['id']}")["workflowExecutionInfo"]
        assert info["status"].endswith("RUNNING"), "sleeping on a Temporal timer"

        cancelled = (await client.post(f"/api/goals/{g['id']}/cancel")).json()
        assert cancelled["status"] == "cancelled"
        async with asyncio.timeout(60):
            while True:
                status = describe("workflow", f"goal-{g['id']}")["workflowExecutionInfo"]["status"]
                if status.endswith("CANCELED"):
                    break
                await asyncio.sleep(1)


async def test_a_recurring_goal_notifies_only_when_the_result_changes():
    async with async_logged_in_client() as client:
        cid = await conversation(client)
        await client.put("/api/profile/memory/test_signal", json={"value": "alpha"})
        created = await client.post(
            "/api/goals",
            json={
                "conversation_id": cid,
                "title": "Signal",
                "objective": "Report the value of the user's profile fact named test_signal, "
                "exactly as written. Use no tools.",
                "every_minutes": 1,
            },
        )
        g = created.json()
        assert describe("schedule", f"goal-{g['id']}"), "a Temporal Schedule drives it"
        try:
            quiet = await until(client, g["id"], lambda x: x["run_count"] >= 2, 420)
            assert quiet["notify_count"] == 0, "baseline and an unchanged value stay quiet"
            assert quiet["last_value"].lower() == "alpha"

            await client.put("/api/profile/memory/test_signal", json={"value": "beta"})
            changed = await until(client, g["id"], lambda x: x["notify_count"] >= 1, 420)
            assert changed["last_value"].lower() == "beta"
            later = await until(
                client, g["id"], lambda x: x["run_count"] >= changed["run_count"] + 1, 300
            )
            assert later["notify_count"] == 1, "no repeat notification while it stays beta"
        finally:
            await client.post(f"/api/goals/{g['id']}/cancel")
        assert describe("schedule", f"goal-{g['id']}") == {}, "cancel deleted the schedule"
        notes = [
            n for n in (await client.get("/api/notifications")).json() if n["goal_id"] == g["id"]
        ]
        assert len(notes) == 1
