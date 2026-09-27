import asyncio
import base64
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from sandboxd.constraints import create_kwargs
from sandboxd.handler import CapacityReached, FileTooLarge, SandboxHandler
from sandboxd.paths import UnsafePath, resolve
from sandboxd.schema import CreateSandbox, ExecRequest, StageRequest


@pytest.mark.parametrize(
    ("given", "expected"),
    [(".", "/workspace"), ("a/b.txt", "/workspace/a/b.txt"), ("/abs.txt", "/workspace/abs.txt")],
)
def test_paths_resolve_inside_the_workspace(given: str, expected: str):
    assert resolve(given) == expected


@pytest.mark.parametrize("given", ["..", "../etc/passwd", "a/../../x", "a\x00b"])
def test_escaping_paths_are_refused(given: str):
    with pytest.raises(UnsafePath):
        resolve(given)


def test_every_mandatory_constraint_is_applied():
    kwargs = create_kwargs("img:1", "k")
    assert kwargs["user"] == "10001:10001"
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["read_only"] is True
    assert kwargs["network_mode"] == "none"
    assert kwargs["pids_limit"] == 256
    assert kwargs["mem_limit"] == "4g"
    assert kwargs["nano_cpus"] == 2_000_000_000
    assert kwargs["privileged"] is False
    assert kwargs["volumes"] == {"lm-ws-k": {"bind": "/workspace", "mode": "rw"}}
    assert set(kwargs["tmpfs"]) == {"/tmp"}
    assert "HOME" in kwargs["environment"] and len(kwargs["environment"]) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"privileged": True},
        {"network_mode": "bridge"},
        {"volumes": {"/": {"bind": "/host"}}},
        {"image": "alpine"},
        {"user": "root"},
    ],
)
def test_callers_cannot_pass_constraints(override: dict[str, Any]):
    with pytest.raises(ValidationError):
        CreateSandbox.model_validate({"topic_id": str(uuid.uuid4()), **override})


def test_exec_timeout_is_bounded():
    with pytest.raises(ValidationError):
        ExecRequest(cmd="sleep 1", timeout_s=10_000)
    with pytest.raises(ValidationError):
        ExecRequest.model_validate({"cmd": "id", "user": "root"})


class FakeEngine:
    def __init__(self, running: set[str]) -> None:
        self.running = running
        self.writes: list[tuple[str, str, bytes]] = []
        self.destroyed: list[str] = []

    async def running_keys(self) -> set[str]:
        return set(self.running)

    async def ensure(self, key: str) -> str:
        if key in self.running:
            return "running"
        self.running.add(key)
        return "created"

    async def destroy(self, key: str) -> None:
        self.running.discard(key)
        self.destroyed.append(key)

    async def exec(self, key: str, cmd: str, timeout_s: int, cwd: str) -> dict[str, object]:
        await asyncio.sleep(0.05)
        return {"stdout": "", "stderr": "", "exit_code": 0, "truncated": False, "timed_out": False}

    async def write_file(self, key: str, path: str, data: bytes) -> None:
        self.writes.append((key, path, data))


def handler(engine: FakeEngine, max_running: int = 2) -> SandboxHandler:
    return SandboxHandler(engine, max_running)  # type: ignore[arg-type]


async def test_at_capacity_the_least_recently_used_idle_sandbox_is_evicted():
    a, b, c = (uuid.uuid4() for _ in range(3))
    engine = FakeEngine(set())
    sandboxes = handler(engine)
    await sandboxes.create(a)
    await sandboxes.create(b)
    await sandboxes.exec(a, ExecRequest(cmd="true"))  # a is now more recent than b

    assert (await sandboxes.create(c)).status == "created"
    assert engine.destroyed == [str(b)]
    assert engine.running == {str(a), str(c)}


async def test_busy_sandboxes_are_never_evicted():
    a, b, c = (uuid.uuid4() for _ in range(3))
    engine = FakeEngine(set())
    sandboxes = handler(engine)
    await sandboxes.create(a)
    await sandboxes.create(b)
    running = [
        asyncio.create_task(sandboxes.exec(a, ExecRequest(cmd="sleep"))),
        asyncio.create_task(sandboxes.exec(b, ExecRequest(cmd="sleep"))),
    ]
    await asyncio.sleep(0)
    with pytest.raises(CapacityReached, match="busy"):
        await sandboxes.create(c)
    await asyncio.gather(*running)
    assert engine.destroyed == []


async def test_stage_lands_in_incoming_with_a_safe_name():
    engine = FakeEngine(set())
    key = uuid.uuid4()
    body = StageRequest(filename="../../etc/pass wd", content_b64=base64.b64encode(b"x").decode())
    path = await handler(engine).stage(key, body)
    assert path == "incoming/pass_wd"
    assert engine.writes == [(str(key), "/workspace/incoming/pass_wd", b"x")]


async def test_oversized_writes_are_refused():
    with pytest.raises(FileTooLarge):
        await handler(FakeEngine(set())).write_file(uuid.uuid4(), "big", b"x" * (11 * 1024 * 1024))
