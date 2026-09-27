"""Phase 8 acceptance: authenticated browser profile, tagging, taint, stricter mutations."""

# ruff: noqa: E501  (long lines are inside scripts executed in the worker container)

import asyncio
import json
import secrets
import uuid
from typing import Any

import httpx
import pytest

from tests.integration.conftest import async_logged_in_client, compose, model_online, sql
from tests.integration.test_sandbox import cleanup
from tests.integration.test_sandbox import in_worker as in_sandbox

pytestmark = [pytest.mark.integration]
TIMEOUT = 300

AUTH_FLOW = """
import asyncio, json, pathlib, uuid, httpx
from muse.browser.controller import BrowserController
from muse.modules.approvals.approvals_controller import ApprovalsController
from muse.modules.approvals.approvals_schema import ApprovalStatus
from muse.modules.artifacts.store import ArtifactStore
from muse.modules.browser.taint import PostgresTaintStore
from muse.policy.engine import PolicyEngine
from muse.sandbox.client import SandboxClient
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
    async with httpx.AsyncClient() as http:
        artifacts = ArtifactStore(engine, pathlib.Path(settings.artifacts_dir))
        browser = BrowserController(engine, artifacts, None, pathlib.Path(settings.browser_profile_dir))
        services = ToolServices(engine=engine, browser=browser, artifacts=artifacts, sandbox=SandboxClient(http, settings))
        ctx = ExecContext(user_id=uuid.UUID("{uid}"), conversation_id=uuid.UUID("{cid}"), workflow_id="test-{cid}")
        policy = PolicyEngine(PostgresDomainAllowlist(engine), PostgresTaintStore(engine))
        gw = ToolGateway(build_registry(), policy, PostgresActionRecorder(engine), services, ctx, PostgresApprovalStore(engine))
        async def call(tool, **args):
            return (await gw.invoke(ToolIntent(tool=tool, args=args))).model_dump(mode="json")
        out = {{}}
        out["open_request"] = await call("browser.open_session", context="authenticated")
        async with engine.begin() as conn:  # the workflow's decide step, done directly
            approval_id = uuid.UUID(out["open_request"]["pending_approval"])
            row = await ApprovalsController(conn).get_row(approval_id)
            await ApprovalsController(conn).decide(approval_id, row["approval_key"], ApprovalStatus.APPROVED, "test", "test")
        out["open"] = await call("browser.open_session", context="authenticated")
        out["sandbox_before"] = await call("sandbox.write_file", path="before.txt", content="clean")
        out["navigate"] = await call("browser.navigate", url="https://www.wikipedia.org")
        snap = await call("browser.snapshot")
        out["snapshot_classification"] = snap["output"]["classification"]
        elements = snap["output"]["elements"]
        box = next(e for e in elements if e["role"] in ("textbox", "searchbox") or "search" in e["name"].lower())
        button = next(e for e in elements if e["role"] == "button")
        out["fill"] = await call("browser.fill", element_id=box["id"], text="Temporal")
        out["click"] = await call("browser.click", element_id=button["id"])
        out["sandbox_after"] = await call("sandbox.write_file", path="page.txt", content=snap["output"]["text"][:200])
        out["remember"] = await call("profile.remember", key="wiki_note", value="Visited Wikipedia")
        shot = await call("browser.screenshot")
        out["screenshot"] = shot
        out["stage"] = await call("sandbox.stage", artifact_id=shot["output"]["artifact_id"])
        out["sandbox_read"] = await call("sandbox.list")
        out["close"] = await call("browser.close_session")
        await SandboxClient(http, settings).destroy_volume(ctx.conversation_id)
        await browser.stop()
    await engine.dispose()
    print(json.dumps(out))

asyncio.run(main())
"""


async def ids(client: httpx.AsyncClient) -> tuple[str, str]:
    user_id: str = (await client.get("/api/auth/me")).json()["id"]
    conversation_id: str = (await client.post("/api/conversations", json={})).json()["id"]
    return user_id, conversation_id


async def test_authenticated_content_is_tagged_and_every_onward_write_needs_approval():
    async with async_logged_in_client() as client:
        uid, cid = await ids(client)
        stdout = compose(
            "exec", "-T", "worker", "python", "-c", AUTH_FLOW.format(uid=uid, cid=cid)
        ).stdout
        r = json.loads(stdout.strip().splitlines()[-1])

    assert r["open_request"]["pending_approval"], "opening the logged-in profile needs approval"
    assert r["open"]["ok"] and r["open"]["output"]["context"] == "authenticated"
    assert r["sandbox_before"]["ok"], "before reading logged-in content, sandbox writes are allowed"
    assert r["navigate"]["ok"]
    assert r["snapshot_classification"] == "AUTHENTICATED"
    assert r["fill"]["pending_approval"], "fill on an authenticated page needs approval"
    assert r["click"]["pending_approval"], "click on an authenticated page needs approval"
    assert r["sandbox_after"]["pending_approval"], (
        "logged-in content cannot reach the sandbox unapproved"
    )
    assert r["remember"]["pending_approval"], "nor profile memory"
    assert r["screenshot"]["ok"]
    assert r["stage"]["pending_approval"], "nor can the authenticated screenshot be staged"
    assert r["sandbox_read"]["ok"], "reading the sandbox is still fine"

    artifact = r["screenshot"]["output"]["artifact_id"]
    assert sql(f"SELECT classification FROM artifacts WHERE id = '{artifact}'") == "AUTHENTICATED"
    rules = sql(
        "SELECT string_agg(DISTINCT proposal->>'tool', ',') FROM actions "
        f"WHERE conversation_id = '{cid}' AND decision = 'REQUIRE_APPROVAL'"
    )
    assert set(rules.split(",")) == {
        "browser.open_session", "browser.fill", "browser.click",
        "sandbox.write_file", "profile.remember", "sandbox.stage",
    }  # fmt: skip
    assert (
        sql(f"SELECT classification FROM data_taint WHERE conversation_id = '{cid}'")
        == "AUTHENTICATED"
    )
    profile = compose(
        "exec", "-T", "worker", "sh", "-c", f"ls /data/browser-profile/{uid}/Default"
    ).stdout
    assert "Cookies" in profile or "Network" in profile, "the persistent profile was written"


def test_the_profile_is_not_reachable_from_a_sandbox():
    sid = uuid.uuid4()
    r = in_sandbox(
        sid,
        """
await c.ensure(sid)
await run("profile_dir", "test -e /data/browser-profile")
await run("artifacts_dir", "test -e /data/artifacts")
await run("cookies", "find / -name Cookies -path '*Default*' 2>/dev/null | head -1")
await run("mounts", "cat /proc/mounts")
""",
    )
    try:
        assert r["profile_dir"]["exit_code"] != 0
        assert r["artifacts_dir"]["exit_code"] != 0
        assert r["cookies"]["stdout"].strip() == ""
        assert "browser-profile" not in r["mounts"]["stdout"]
    finally:
        cleanup(sid)


async def state(client: httpx.AsyncClient, conversation_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/conversations/{conversation_id}/state")).json()
    return body


async def test_typed_text_never_enters_temporal_history():
    if not model_online():
        pytest.skip("local model not online")
    secret_text = f"pw-{secrets.token_hex(6)}"
    async with async_logged_in_client() as client:
        _, cid = await ids(client)
        await client.post(
            f"/api/conversations/{cid}/messages",
            json={
                "content": "Open a logged-in (authenticated) browser session with browser_open_session. Nothing else."
            },
        )
        async with asyncio.timeout(TIMEOUT):
            while True:
                current = await state(client, cid)
                pending = [a for a in current["approvals"] if a["status"] == "PENDING"]
                if pending:
                    break
                await asyncio.sleep(1)
        assert pending[0]["tool"] == "browser.open_session"
        await client.post(
            f"/api/approvals/{pending[0]['id']}/decision",
            json={"decision": "approve", "approval_key": pending[0]["approval_key"]},
        )
        async with asyncio.timeout(TIMEOUT):
            while True:
                current = await state(client, cid)
                sessions = [
                    b for b in current["browser_sessions"] if b["context"] == "authenticated"
                ]
                if sessions and not current["status"]["running_turn_id"]:
                    break
                await asyncio.sleep(1)
        session = sessions[0]["id"]
        assert (
            await client.post(f"/api/browser/{session}/mode", json={"mode": "human"})
        ).status_code == 204
        await client.post(
            f"/api/browser/{session}/input", json={"kind": "navigate", "url": "https://example.com"}
        )
        typed = await client.post(
            f"/api/browser/{session}/input", json={"kind": "type", "text": secret_text}
        )
        assert typed.status_code == 200
        await client.post(f"/api/browser/{session}/mode", json={"mode": "agent"})

    history = compose(
        "exec", "-T", "temporal", "temporal", "workflow", "show", "-w", f"conv-{cid}",
        "--address", "temporal:7233", "-o", "json",
    ).stdout  # fmt: skip
    assert "browser_human_input" in history, "the input did go through the workflow"
    assert secret_text not in history
    assert int(sql("SELECT count(*) FROM browser_input_inbox") or 0) == 0
    audit = sql(
        f"SELECT string_agg(payload::text, ' ') FROM audit_events WHERE event_type = 'browser.human_input' AND conversation_id = '{cid}'"
    )
    assert secret_text not in audit and '"kind": "type"' in audit
