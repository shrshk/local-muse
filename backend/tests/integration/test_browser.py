"""Phase 7 acceptance: research browsing, allowlist-gated clicks, network guard, human takeover."""

# ruff: noqa: E501  (long lines are inside scripts executed in the worker container)

import asyncio
import json
from typing import Any

import httpx
import pytest

from tests.integration.conftest import async_logged_in_client, compose, model_online

pytestmark = [pytest.mark.integration]
TIMEOUT = 300

GATEWAY = """
import asyncio, json, pathlib, uuid
from muse.browser.controller import BrowserController
from muse.modules.artifacts.store import ArtifactStore
from muse.policy.engine import PolicyEngine
from muse.shared.db import create_engine
from muse.shared.settings import get_settings
from muse.tools.approvals import PostgresApprovalStore, PostgresDomainAllowlist
from muse.tools.gateway import ToolGateway
from muse.tools.recorder import PostgresActionRecorder
from muse.tools.schema import ExecContext, ToolIntent, ToolServices
from muse.tools.specs import build_registry

async def main():
    settings = get_settings()
    engine = create_engine(settings)
    browser = BrowserController(engine, ArtifactStore(engine, pathlib.Path(settings.artifacts_dir)), None)
    ctx = ExecContext(user_id=uuid.UUID("{uid}"), conversation_id=uuid.UUID("{cid}"), workflow_id="test-{cid}")
    gw = ToolGateway(build_registry(), PolicyEngine(PostgresDomainAllowlist(engine)), PostgresActionRecorder(engine),
                     ToolServices(engine=engine, browser=browser), ctx, PostgresApprovalStore(engine))
    async def call(tool, **args):
        return (await gw.invoke(ToolIntent(tool=tool, args=args))).model_dump(mode="json")
    out = {{}}
{body}
    await browser.stop()
    await engine.dispose()
    print(json.dumps(out))

asyncio.run(main())
"""


def in_worker(uid: str, cid: str, body: str) -> dict[str, Any]:
    indented = "\n".join("    " + line for line in body.strip().splitlines())
    stdout = compose(
        "exec", "-T", "worker", "python", "-c", GATEWAY.format(uid=uid, cid=cid, body=indented)
    ).stdout
    result: dict[str, Any] = json.loads(stdout.strip().splitlines()[-1])
    return result


CLICK_FIRST_LINK = """
out["nav"] = await call("browser.navigate", url="https://example.com")
snap = await call("browser.snapshot")
link = next(e for e in snap["output"]["elements"] if e["role"] == "link")
out["link"] = link
out["click"] = await call("browser.click", element_id=link["id"])
"""


async def ids(client: httpx.AsyncClient) -> tuple[str, str]:
    user_id: str = (await client.get("/api/auth/me")).json()["id"]
    conversation_id: str = (await client.post("/api/conversations", json={})).json()["id"]
    return user_id, conversation_id


async def test_click_needs_approval_until_the_domain_is_allowlisted():
    async with async_logged_in_client() as client:
        uid, cid = await ids(client)
        before = in_worker(uid, cid, CLICK_FIRST_LINK)
        assert before["nav"]["ok"]
        assert before["click"]["pending_approval"], (
            "click on a non-allowlisted domain needs approval"
        )

        assert (
            await client.put("/api/allowlist", json={"domain": "example.com"})
        ).status_code == 204
        try:
            after = in_worker(uid, cid, CLICK_FIRST_LINK)
        finally:
            await client.delete("/api/allowlist/example.com")
        assert after["click"]["ok"], after["click"]
        assert "example.com" not in after["click"]["output"]["url"], "the link was followed"

        approval = (await client.get("/api/approvals", params={"status": "PENDING"})).json()[0]
        assert approval["tool"] == "browser.click"
        assert approval["destination"] == "example.com"


async def test_browser_cannot_reach_internal_services_or_local_files():
    async with async_logged_in_client() as client:
        uid, cid = await ids(client)
        r = in_worker(
            uid,
            cid,
            """
for name, url in [("temporal_ui", "http://temporal-ui:8080"), ("ollama", "http://host.docker.internal:11434"),
                  ("sandboxd", "http://sandboxd:8080/health"), ("loopback", "http://127.0.0.1:8000"),
                  ("metadata", "http://169.254.169.254/latest/meta-data/"), ("file", "file:///etc/passwd")]:
    out[name] = await call("browser.navigate", url=url)
""",
        )
    for name, result in r.items():
        assert not result["ok"], (name, result)
        assert "public" in result["error"] or "only http" in result["error"], (name, result)


async def state(client: httpx.AsyncClient, conversation_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/conversations/{conversation_id}/state")).json()
    return body


async def send_and_wait(
    client: httpx.AsyncClient, conversation_id: str, text: str
) -> dict[str, Any]:
    await client.post(f"/api/conversations/{conversation_id}/messages", json={"content": text})
    return await settle(client, conversation_id)


async def settle(client: httpx.AsyncClient, conversation_id: str) -> dict[str, Any]:
    async with asyncio.timeout(TIMEOUT):
        while True:
            current = await state(client, conversation_id)
            s = current["status"]
            if (
                current["messages"][-1]["role"] == "assistant"
                and not s["running_turn_id"]
                and not s["pending_turn_ids"]
            ):
                return current
            await asyncio.sleep(1)


async def test_agent_completes_a_public_research_task():
    if not model_online():
        pytest.skip("local model not online")
    async with async_logged_in_client() as client:
        _, cid = await ids(client)
        done = await send_and_wait(
            client,
            cid,
            "Use the browser to open https://example.com and tell me the page's main heading.",
        )
    assert "example domain" in done["messages"][-1]["content"].lower()
    tools = [(a["tool"], a["status"]) for a in done["actions"]]
    assert ("browser.navigate", "executed") in tools
    assert ("browser.snapshot", "executed") in tools
    assert done["browser_sessions"][0]["frame_version"] >= 1


async def test_takeover_pauses_the_agent_and_it_resumes_after():
    if not model_online():
        pytest.skip("local model not online")
    async with async_logged_in_client() as client:
        _, cid = await ids(client)
        await send_and_wait(
            client, cid, "Use the browser to open https://example.com. Just say done."
        )
        session = cid  # the coordinator's browser session is keyed by conversation

        early = await client.post(f"/api/browser/{session}/input", json={"kind": "scroll"})
        assert early.status_code == 409, "no human input without control"
        assert (
            await client.post(f"/api/browser/{session}/mode", json={"mode": "human"})
        ).status_code == 204
        moved = await client.post(
            f"/api/browser/{session}/input",
            json={"kind": "navigate", "url": "https://www.iana.org/help/example-domains"},
        )
        assert moved.status_code == 200 and "iana.org" in moved.json()["url"]

        await client.post(
            f"/api/conversations/{cid}/messages",
            json={
                "content": "Take a snapshot of the page open in the browser right now and tell me its main heading. Do not navigate."
            },
        )
        async with asyncio.timeout(TIMEOUT):
            while True:
                current = await state(client, cid)
                deferred = [a for a in current["actions"] if a["status"] == "deferred"]
                if deferred:
                    break
                await asyncio.sleep(1)
        paused_at = deferred[0]["created_at"]
        await asyncio.sleep(3)
        current = await state(client, cid)
        executed_while_human = [
            a
            for a in current["actions"]
            if a["tool"].startswith("browser.")
            and a["status"] == "executed"
            and a["created_at"] > paused_at
        ]
        assert executed_while_human == [], "the agent did not act while the human had control"
        assert current["status"]["running_turn_id"], "the turn is waiting, not finished"

        assert (
            await client.post(f"/api/browser/{session}/mode", json={"mode": "agent"})
        ).status_code == 204
        done = await settle(client, cid)

    resumed = [
        a
        for a in done["actions"]
        if a["tool"].startswith("browser.")
        and a["status"] == "executed"
        and a["created_at"] > paused_at
    ]
    assert resumed, "the agent acted again after control came back"
    assert done["browser_sessions"][0]["mode"] == "agent"
