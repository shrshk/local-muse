"""Phase 2 acceptance: the local model answers and calls clock.now through the gateway."""

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


def test_local_model_calls_clock_through_the_gateway(client: httpx.Client):
    if client.get("/api/models/health").json()["status"] != "online":
        pytest.skip("local model not online")
    conversation = client.post("/api/conversations", json={}).json()

    turn = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": "What is the current time in Asia/Tokyo? Use the clock tool."},
    )
    assert turn.status_code == 200, turn.text
    body = turn.json()
    assert body["assistant_message"]["content"].strip()

    clock_calls = [c for c in body["tool_calls"] if c["tool"] == "clock.now"]
    assert clock_calls, body
    assert clock_calls[0]["decision"] == "ALLOW"
    assert clock_calls[0]["ok"] is True

    actions = client.get(f"/api/conversations/{conversation['id']}/actions").json()
    recorded = next(a for a in actions if a["action_id"] == clock_calls[0]["action_id"])
    assert recorded["status"] == "executed"
    assert recorded["decision"] == "ALLOW"

    events = sql(
        "SELECT string_agg(event_type, ',' ORDER BY id) FROM audit_events "
        f"WHERE action_id = '{recorded['action_id']}'"
    )
    assert events == "action.proposed,action.decided,action.executed"
