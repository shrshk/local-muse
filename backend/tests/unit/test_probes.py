from collections.abc import Callable
from typing import Any

import httpx
import pytest

from muse.modules.health.health_schema import ComponentStatus
from muse.modules.health.probes import CentrifugoProbe, ModelProbe, SandboxdProbe
from muse.sandbox.client import SandboxClient
from muse.shared.settings import Settings

SETTINGS = Settings(
    model_name="qwen3:30b-a3b",
    centrifugo_api_key="api-key",
    sandboxd_token="sandbox-token",
)


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def tags(*names: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _: httpx.Response(200, json={"models": [{"name": n} for n in names]})


def refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (tags("qwen3:30b-a3b"), ComponentStatus.ONLINE),
        (tags("llama3:8b"), ComponentStatus.DEGRADED),
        (refuse, ComponentStatus.OFFLINE),
        (lambda _: httpx.Response(500), ComponentStatus.OFFLINE),
    ],
)
async def test_model_probe(handler: Any, expected: ComponentStatus):
    status, _ = await ModelProbe(client(handler), SETTINGS).check()
    assert status is expected


async def test_model_probe_tells_you_what_to_pull():
    _, detail = await ModelProbe(client(tags()), SETTINGS).check()
    assert detail == "run: ollama pull qwen3:30b-a3b"


async def test_centrifugo_probe_sends_api_key():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["X-API-Key"]
        return httpx.Response(200, json={"result": {}})

    status, _ = await CentrifugoProbe(client(handler), SETTINGS).check()
    assert status is ComponentStatus.ONLINE
    assert seen["key"] == "api-key"


async def test_centrifugo_probe_bad_key_is_degraded():
    status, _ = await CentrifugoProbe(client(lambda _: httpx.Response(401)), SETTINGS).check()
    assert status is ComponentStatus.DEGRADED


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (lambda _: httpx.Response(200, json={"docker": "ok"}), ComponentStatus.ONLINE),
        (lambda _: httpx.Response(200, json={"docker": "unreachable"}), ComponentStatus.DEGRADED),
        (lambda _: httpx.Response(401), ComponentStatus.OFFLINE),
        (refuse, ComponentStatus.OFFLINE),
    ],
)
async def test_sandboxd_probe(handler: Any, expected: ComponentStatus):
    probe = SandboxdProbe(SandboxClient(client(handler), SETTINGS), timeout_seconds=1)
    status, _ = await probe.check()
    assert status is expected


async def test_sandbox_client_sends_bearer_token():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"docker": "ok"})

    await SandboxClient(client(handler), SETTINGS).health()
    assert seen["auth"] == "Bearer sandbox-token"
