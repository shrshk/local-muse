"""Phase 1 acceptance: every service reports, realtime auth works, isolation holds."""

import json
import subprocess

import httpx
import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from tests.integration.conftest import WEB_URL, compose, container_id

pytestmark = pytest.mark.integration

CORE = {"backend", "postgres", "temporal", "centrifugo", "worker", "worker-model", "sandboxd"}
SERVICES = [
    "postgres", "temporal", "temporal-ui", "centrifugo", "backend",
    "worker", "worker-model", "sandboxd", "web",
]  # fmt: skip
WS_URL = WEB_URL.replace("http", "ws", 1) + "/connection/websocket"


def health() -> dict[str, dict[str, str]]:
    report = httpx.get(f"{WEB_URL}/api/health", timeout=10).json()
    return {c["name"]: c for c in report["components"]}


def test_every_core_component_is_online():
    components = health()
    assert CORE | {"model"} <= set(components)
    offline = {
        n: c["detail"] for n, c in components.items() if n in CORE and c["status"] != "online"
    }
    assert offline == {}


def test_model_is_reported_with_a_known_status():
    assert health()["model"]["status"] in {"online", "degraded", "offline"}


async def connect(token: str) -> dict[str, object]:
    async with websockets.connect(WS_URL, origin=WEB_URL) as ws:  # type: ignore[arg-type]
        await ws.send(json.dumps({"id": 1, "connect": {"token": token}}))
        reply: dict[str, object] = json.loads(await ws.recv())
        return reply


@pytest.fixture
def realtime_token(client: httpx.Client) -> str:
    token: str = client.post("/api/realtime/token").json()["token"]
    return token


async def test_centrifugo_accepts_a_backend_token(realtime_token: str):
    reply = await connect(realtime_token)
    assert "connect" in reply, reply


async def test_centrifugo_rejects_a_forged_token():
    forged = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJvd25lciJ9."
        "c2lnbmF0dXJlLW5vdC1mcm9tLXRoZS1iYWNrZW5k"
    )
    try:
        reply = await connect(forged)
    except ConnectionClosed as closed:
        assert closed.rcvd is not None and closed.rcvd.code == 3500  # invalid token
    else:
        assert "error" in reply, reply


def inspect(service: str) -> dict[str, object]:
    out = subprocess.run(
        ["docker", "inspect", container_id(service)], check=True, capture_output=True, text=True
    )
    info: dict[str, object] = json.loads(out.stdout)[0]
    return info


def test_only_sandboxd_container_has_the_docker_socket():
    for service in SERVICES:
        sources = {m["Source"] for m in inspect(service)["Mounts"]}  # type: ignore[index]
        has_socket = "/var/run/docker.sock" in sources
        assert has_socket == (service == "sandboxd"), service


def test_every_running_container_has_a_memory_limit():
    for service in SERVICES:
        assert inspect(service)["HostConfig"]["Memory"] > 0, service  # type: ignore[index]


def python_in(service: str, code: str) -> subprocess.CompletedProcess[str]:
    return compose("exec", "-T", service, "python", "-c", code, check=False)


def test_backend_cannot_reach_sandboxd():
    result = python_in("backend", "import socket; socket.getaddrinfo('sandboxd', 8080)")
    assert result.returncode != 0
    assert "gaierror" in result.stderr


def test_worker_reaches_sandboxd_only_with_the_token():
    code = (
        "import os, httpx; u='http://sandboxd:8080/health';"
        "h={'Authorization': 'Bearer ' + os.environ['SANDBOXD_TOKEN']};"
        "print(httpx.get(u).status_code, httpx.get(u, headers=h).status_code)"
    )
    result = python_in("worker", code)
    assert result.stdout.split() == ["401", "200"], result.stderr


def test_sandboxd_has_no_egress():
    code = "import socket; socket.create_connection(('1.1.1.1', 53), timeout=2)"
    result = python_in("sandboxd", code)
    assert result.returncode != 0


def test_migrations_are_at_head():
    current = compose("exec", "-T", "backend", "alembic", "current").stdout
    assert "(head)" in current
