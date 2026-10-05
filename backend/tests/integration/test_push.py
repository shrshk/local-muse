"""Phase 11 push acceptance, against a fake push service (test-only compose overlay)."""

import asyncio
import base64
import json
import os
import secrets
import subprocess
from collections.abc import AsyncIterator, Iterator
from typing import Any

import http_ece
import httpx
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from tests.integration.conftest import COMPOSE, ROOT, WEB_URL, compose, create_user, sql

pytestmark = [pytest.mark.integration]

MOCK = "http://127.0.0.1:18082"
OVERLAY = [*COMPOSE, "-f", str(ROOT / "infra/docker-compose.push-test.yml")]
TIMEOUT = 60


def overlay(*args: str) -> None:
    subprocess.run([*OVERLAY, *args], check=True, capture_output=True, text=True, env=os.environ)


@pytest.fixture(scope="module", autouse=True)
def push_mock() -> Iterator[None]:
    overlay("up", "-d", "--wait", "push-mock", "backend")
    try:
        yield
    finally:
        compose("up", "-d", "--wait", "backend")  # back to the normal configuration
        overlay("rm", "-sf", "push-mock")


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    username, password = create_user()
    async with httpx.AsyncClient(base_url=WEB_URL, timeout=30) as c:
        async with asyncio.timeout(60):
            while True:
                try:
                    login = await c.post(
                        "/api/auth/login", json={"username": username, "password": password}
                    )
                    if login.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
        yield c


class Device:
    """A browser's side of a push subscription: its keys and its endpoint at the mock."""

    def __init__(self) -> None:
        self.sub_id = secrets.token_hex(8)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)

    def subscription(self) -> dict[str, Any]:
        public = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
        return {
            "endpoint": f"http://push-mock:8082/p/{self.sub_id}",
            "keys": {"p256dh": b64(public), "auth": b64(self.auth)},
        }

    def decrypt(self, entry: dict[str, Any]) -> dict[str, Any]:
        plain = http_ece.decrypt(
            bytes.fromhex(entry["body"]),
            private_key=self.key,
            auth_secret=self.auth,
            version="aes128gcm",
        )
        payload: dict[str, Any] = json.loads(plain)
        return payload


async def received(device: Device) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as mock:
        entries: list[dict[str, Any]] = (await mock.get(f"{MOCK}/__test/received")).json()
    return [e for e in entries if e["sub"] == device.sub_id]


async def wait_for(predicate: Any) -> Any:
    async with asyncio.timeout(TIMEOUT):
        while True:
            value = await predicate()
            if value:
                return value
            await asyncio.sleep(1)


async def subscribe(client: httpx.AsyncClient, device: Device) -> None:
    response = await client.post("/api/push/subscriptions", json=device.subscription())
    assert response.status_code == 204, response.text


def push_status(notification_id: str) -> str:
    return sql(
        f"SELECT coalesce(push_status, '') FROM notifications WHERE id = '{notification_id}'"
    )


async def test_push_carries_only_an_id_and_the_app_fetches_the_text(client: httpx.AsyncClient):
    device = Device()
    await subscribe(client, device)
    assert (await client.post("/api/push/test")).status_code == 202

    (entry,) = await wait_for(lambda: received(device))
    assert entry["headers"]["authorization"].startswith("vapid t=")
    assert entry["headers"]["content-encoding"] == "aes128gcm"
    payload = device.decrypt(entry)
    assert set(payload) == {"id"}, "nothing but the id travels through the push service"

    shown = (await client.get(f"/api/notifications/{payload['id']}")).json()
    assert shown["title"] == "Test notification" and shown["body"] == "Push works."
    assert push_status(payload["id"]) == "sent"


async def test_budget_holds_muted_kinds_and_feedback_retunes(client: httpx.AsyncClient):
    device = Device()
    await subscribe(client, device)
    user_id = (await client.get("/api/auth/me")).json()["id"]
    muted = await client.put(
        "/api/notification_preferences/goal", json={"level": "none", "daily_cap": 10}
    )
    assert muted.json()["level"] == "none"

    def goal_notification(importance: str) -> str:
        return sql(
            "INSERT INTO notifications (user_id, kind, title, body, importance) "
            f"VALUES ('{user_id}', 'goal', 'Goal t', 'b', '{importance}') RETURNING id"
        ).splitlines()[0]

    held = goal_notification("high")
    await wait_for(lambda: asyncio.sleep(0, push_status(held) == "held"))
    assert await received(device) == [], "muted kind: feed only, no push"

    tuned = await client.post(f"/api/notifications/{held}/feedback", json={"signal": "more"})
    assert tuned.json()["level"] == "important"
    normal = goal_notification("normal")
    await wait_for(lambda: asyncio.sleep(0, push_status(normal) == "held"))
    high = goal_notification("high")
    await wait_for(lambda: asyncio.sleep(0, push_status(high) == "sent"))
    pushed = [device.decrypt(e)["id"] for e in await received(device)]
    assert pushed == [high], "important only: the high-importance one pushes"


async def test_gone_subscriptions_are_dropped(client: httpx.AsyncClient):
    device = Device()
    await subscribe(client, device)
    async with httpx.AsyncClient() as mock:
        await mock.post(f"{MOCK}/__test/gone/{device.sub_id}")
    await client.post("/api/push/test")

    async def dropped() -> bool:
        return (await client.get("/api/push/subscriptions")).json() == []

    assert await wait_for(dropped)


@pytest.mark.parametrize(
    "endpoint",
    ["http://sandboxd:8080/sandboxes", "http://postgres:5432/", "https://temporal-ui:8080/"],
)
async def test_subscriptions_to_internal_services_are_refused(
    client: httpx.AsyncClient, endpoint: str
):
    body = {**Device().subscription(), "endpoint": endpoint}
    response = await client.post("/api/push/subscriptions", json=body)
    assert response.status_code == 422
