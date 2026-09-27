"""Phase 10 acceptance, against a fake Telegram API (test-only compose overlay)."""

# ruff: noqa: E501

import asyncio
import os
import secrets
import subprocess
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from tests.integration.conftest import COMPOSE, ROOT, WEB_URL, compose, model_online, sql

pytestmark = [pytest.mark.integration]

MOCK = "http://127.0.0.1:18081"
CHAT = 111
STRANGER = 999
OVERLAY = [*COMPOSE, "-f", str(ROOT / "infra/docker-compose.telegram-test.yml")]
SEND_ONLY = "Use the outbox tool to send bob@example.com the message 'Running late'."
TIMEOUT = 300


def overlay(*args: str, env: dict[str, str]) -> None:
    subprocess.run([*OVERLAY, *args], check=True, capture_output=True, text=True, env=env)


@pytest.fixture(scope="module")
def owner() -> Iterator[tuple[str, str]]:
    username, password = f"itest-tg-{secrets.token_hex(4)}", secrets.token_urlsafe(18)
    compose(
        "exec", "-T", "backend", "python", "-m", "muse.cli", "create-user",
        "--username", username, "--password-stdin", stdin=password + "\n",
    )  # fmt: skip
    env = {**os.environ, "TELEGRAM_OWNER_USERNAME": username}
    overlay("up", "-d", "--wait", "telegram-mock", "backend", env=env)
    try:
        yield username, password
    finally:
        compose("up", "-d", "--wait", "backend")  # back to the normal configuration
        overlay("rm", "-sf", "telegram-mock", env=env)


@pytest_asyncio.fixture
async def client(owner: tuple[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=WEB_URL, timeout=60) as c:
        async with asyncio.timeout(60):
            while True:
                try:
                    login = await c.post(
                        "/api/auth/login", json={"username": owner[0], "password": owner[1]}
                    )
                    if login.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
        yield c


async def telegram_log() -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as mock:
        entries: list[dict[str, Any]] = (await mock.get(f"{MOCK}/__test/log")).json()
        return entries


async def inject(update: dict[str, Any]) -> None:
    async with httpx.AsyncClient() as mock:
        await mock.post(f"{MOCK}/__test/updates", json=update)


async def wait_log(predicate: Any) -> dict[str, Any]:
    async with asyncio.timeout(TIMEOUT):
        while True:
            for entry in await telegram_log():
                if predicate(entry):
                    return entry
            await asyncio.sleep(1)


def callback(data: str, message_id: int, chat: int = CHAT) -> dict[str, Any]:
    return {
        "callback_query": {
            "id": secrets.token_hex(4),
            "data": data,
            "message": {"message_id": message_id, "chat": {"id": chat}, "text": "Approval needed"},
        }
    }


def text_message(text: str, chat: int) -> dict[str, Any]:
    return {"message": {"message_id": 1, "chat": {"id": chat}, "text": text}}


async def test_approving_from_telegram_resumes_the_workflow_and_duplicates_are_harmless(
    client: httpx.AsyncClient,
):
    if not model_online():
        pytest.skip("local model not online")
    cid = (await client.post("/api/conversations", json={})).json()["id"]
    await client.post(f"/api/conversations/{cid}/messages", json={"content": SEND_ONLY})

    sent = await wait_log(
        lambda e: (
            e["method"] == "sendMessage" and "reply_markup" in e and "bob@example.com" in e["text"]
        )
    )
    assert sent["chat_id"] == CHAT
    approve = sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    message_id = sent["message_id"]

    await inject(callback(approve, message_id))
    answer = await wait_log(lambda e: e["method"] == "answerCallbackQuery")
    assert answer["text"] == "Approved."

    async with asyncio.timeout(TIMEOUT):
        while True:
            state = (await client.get(f"/api/conversations/{cid}/state")).json()
            if (
                state["messages"][-1]["role"] == "assistant"
                and not state["status"]["running_turn_id"]
            ):
                break
            await asyncio.sleep(1)
    assert int(sql(f"SELECT count(*) FROM outbox WHERE conversation_id = '{cid}'")) == 1
    approval = state["approvals"][0]
    assert approval["status"] == "APPROVED" and approval["channel"] == "telegram"

    await inject(callback(approve, message_id))
    duplicate = await wait_log(
        lambda e: e["method"] == "answerCallbackQuery" and e["text"].startswith("Already decided")
    )
    assert "approved" in duplicate["text"]
    assert int(sql(f"SELECT count(*) FROM outbox WHERE conversation_id = '{cid}'")) == 1
    assert any(e["method"] == "editMessageText" for e in await telegram_log())


async def test_unknown_chats_are_ignored_and_audited(client: httpx.AsyncClient):
    await inject(text_message("/status", STRANGER))
    await inject(callback(f"a:{secrets.token_hex(16)}:x:y", 5, chat=STRANGER))
    query = f"SELECT count(*) FROM audit_events WHERE actor = 'telegram:{STRANGER}' AND event_type = 'telegram.ignored'"
    async with asyncio.timeout(60):
        while True:
            if int(sql(query)) >= 2:
                break
            await asyncio.sleep(1)
    assert not any(e.get("chat_id") == STRANGER for e in await telegram_log())


async def test_status_and_forged_callbacks_from_the_owner_chat(client: httpx.AsyncClient):
    await inject(text_message("/status", CHAT))
    status = await wait_log(
        lambda e: e["method"] == "sendMessage" and "Pending approvals:" in e["text"]
    )
    assert status["chat_id"] == CHAT
    forged = "a:00000000-0000-0000-0000-000000000000:0000000000000000:y"
    await inject(callback(forged, 5))
    answer = await wait_log(
        lambda e: e["method"] == "answerCallbackQuery" and e["text"] == "Not found."
    )
    assert answer
