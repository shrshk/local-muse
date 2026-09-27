"""Phase 2 acceptance: the local model answers and calls clock.now through the gateway."""

import time

import httpx
import pytest

from tests.integration.conftest import WEB_URL, compose, logged_in_client, sql

pytestmark = pytest.mark.integration


def test_protected_endpoints_require_login():
    with httpx.Client(base_url=WEB_URL) as anon:
        assert anon.get("/api/conversations").status_code == 401
        assert anon.post("/api/realtime/token").status_code == 401
        assert anon.get("/api/auth/me").status_code == 401


def test_wrong_password_is_rejected():
    with httpx.Client(base_url=WEB_URL) as anon:
        response = anon.post("/api/auth/login", json={"username": "owner", "password": "wrong"})
    assert response.status_code == 401


def test_conversations_are_private_to_their_owner(client: httpx.Client):
    conversation = client.post("/api/conversations", json={}).json()
    with logged_in_client() as other:
        assert other.get(f"/api/conversations/{conversation['id']}/messages").status_code == 404


def test_model_runs_locally_with_no_cloud_keys(client: httpx.Client):
    health = client.get("/api/models/health").json()
    assert health["provider"] == "ollama"
    env = compose("exec", "-T", "backend", "env").stdout
    assert "LOCAL_MUSE_MODE=offline" in env
    assert "host.docker.internal:11434" in env
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
        assert f"{key}=" not in env


def wait_for_reply(client: httpx.Client, conversation_id: str, timeout: float = 240) -> dict:  # type: ignore[type-arg]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/api/conversations/{conversation_id}/state").json()
        if any(m["role"] == "assistant" for m in state["messages"]):
            return state  # type: ignore[no-any-return]
        time.sleep(1)
    raise AssertionError(f"no reply within {timeout}s: {state['status']}")


def test_local_model_calls_clock_through_the_gateway(client: httpx.Client):
    if client.get("/api/models/health").json()["status"] != "online":
        pytest.skip("local model not online")
    conversation = client.post("/api/conversations", json={}).json()

    ack = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": "What is the current time in Asia/Tokyo? Use the clock tool."},
    )
    assert ack.status_code == 202, ack.text
    state = wait_for_reply(client, conversation["id"])

    assert state["messages"][0]["id"] == ack.json()["message_id"]
    assert state["messages"][-1]["content"].strip()
    clock = [a for a in state["actions"] if a["tool"] == "clock.now"]
    assert clock, state
    assert clock[0]["decision"] == "ALLOW"
    assert clock[0]["status"] == "executed"
    assert clock[0]["args"] == {"timezone": "Asia/Tokyo"}

    events = sql(
        "SELECT string_agg(event_type, ',' ORDER BY id) FROM audit_events "
        f"WHERE action_id = '{clock[0]['action_id']}'"
    )
    assert events == "action.proposed,action.decided,action.executed"
