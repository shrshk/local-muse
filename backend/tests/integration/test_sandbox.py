"""Phase 5 acceptance: sandbox isolation, persistence, limits, and the sandbox tools."""

# ruff: noqa: E501  (long lines are inside scripts executed in the worker container)

import asyncio
import json
import subprocess
import uuid
from typing import Any

import pytest

from tests.integration.conftest import async_logged_in_client, compose, model_online, sql

pytestmark = [pytest.mark.integration]

RUNNER = """
import asyncio, json, uuid, httpx
from muse.shared.settings import get_settings
from muse.sandbox.client import SandboxClient, SandboxError

async def main():
    out = {{}}
    async with httpx.AsyncClient() as http:
        c = SandboxClient(http, get_settings())
        sid = uuid.UUID("{sid}")
        async def run(name, cmd, t=30):
            out[name] = await c.exec(sid, cmd, t, ".")
{body}
    print(json.dumps(out))

asyncio.run(main())
"""


def in_worker(sid: uuid.UUID, body: str) -> dict[str, Any]:
    indented = "\n".join("        " + line for line in body.strip().splitlines())
    script = RUNNER.format(sid=sid, body=indented)
    stdout = compose("exec", "-T", "worker", "python", "-c", script).stdout
    result: dict[str, Any] = json.loads(stdout.strip().splitlines()[-1])
    return result


def cleanup(*sids: uuid.UUID) -> None:
    body = "\n".join(f'await c.destroy_volume(uuid.UUID("{s}"))' for s in sids)
    in_worker(sids[0], body)


@pytest.fixture
def sid() -> Any:
    sandbox_id = uuid.uuid4()
    yield sandbox_id
    cleanup(sandbox_id)


def test_sandbox_is_isolated(sid: uuid.UUID):
    r = in_worker(
        sid,
        """
await c.ensure(sid)
await run("id", "id -u")
await run("caps", "grep CapEff /proc/self/status")
await run("socket", "test -e /var/run/docker.sock")
await run("mounts", "cat /proc/mounts")
await run("host_home", "ls /Users /root/.ssh /home 2>&1; test -e /Users")
await run("dns", "python -c \\"import socket; socket.getaddrinfo('example.com', 80)\\"")
await run("tcp", "python -c \\"import socket; socket.create_connection(('1.1.1.1', 53), 3)\\"")
await run("curl", "curl -sS --max-time 5 http://1.1.1.1")
await run("ifaces", "for i in /sys/class/net/*/flags; do echo $(basename $(dirname $i)) $(cat $i); done")
await run("routes", "tail -n +2 /proc/net/route")
await run("env", "env")
await run("ro_usr", "touch /usr/local/x")
await run("ro_etc", "touch /etc/x")
await run("tmp_noexec", "printf '#!/bin/sh\\\\necho hi' > /tmp/x.sh && chmod +x /tmp/x.sh && /tmp/x.sh")
await run("workspace", "echo ok > /workspace/probe && cat /workspace/probe")
""",
    )
    assert r["id"]["stdout"].strip() == "10001"
    assert r["caps"]["stdout"].split()[-1] == "0000000000000000"
    assert r["socket"]["exit_code"] != 0
    assert "docker.sock" not in r["mounts"]["stdout"]
    assert "/Users" not in r["mounts"]["stdout"]
    assert r["host_home"]["exit_code"] != 0
    for probe in ("dns", "tcp", "curl"):
        assert r[probe]["exit_code"] != 0, probe
    # Docker Desktop's kernel leaves stub tunnel interfaces in every netns; only lo may be up.
    up = [
        name
        for name, flags in (line.split() for line in r["ifaces"]["stdout"].splitlines())
        if int(flags, 16) & 0x1
    ]
    assert up == ["lo"]
    assert r["routes"]["stdout"].strip() == "", "no routes at all"
    env_keys = {line.split("=", 1)[0] for line in r["env"]["stdout"].splitlines()}
    assert not any(
        k.startswith(("SANDBOXD", "POSTGRES", "CENTRIFUGO", "SESSION", "DATABASE"))
        for k in env_keys
    )
    for probe in ("ro_usr", "ro_etc"):
        assert r[probe]["exit_code"] != 0 and "Read-only" in r[probe]["stderr"], probe
    assert r["tmp_noexec"]["exit_code"] != 0
    assert r["workspace"]["stdout"].strip() == "ok"


def test_workspace_survives_container_recreation(sid: uuid.UUID):
    r = in_worker(
        sid,
        """
await c.ensure(sid)
await c.write_file(sid, "notes/keep.txt", b"persisted")
await run("before", "cat /proc/sys/kernel/hostname")
await c.destroy(sid)
await c.ensure(sid)
await run("after", "cat /proc/sys/kernel/hostname")
out["content"] = (await c.read_file(sid, "notes/keep.txt")).decode()
out["listing"] = await c.list_dir(sid, "notes")
""",
    )
    assert r["before"]["stdout"] != r["after"]["stdout"], "a fresh container was created"
    assert r["content"] == "persisted"
    assert [e["name"] for e in r["listing"]] == ["keep.txt"]


def test_pid_and_memory_limits_are_enforced(sid: uuid.UUID):
    r = in_worker(
        sid,
        """
await c.ensure(sid)
await run("pids_max", "cat /sys/fs/cgroup/pids.max")
await run("mem_max", "cat /sys/fs/cgroup/memory.max")
await run("oom", "python -c \\"chunks = [bytearray(256 * 1024 ** 2) for _ in range(24)]; [c.__setitem__(slice(None, None, 4096), b'x' * (len(c) // 4096)) for c in chunks]\\"", 120)
await run("oom_events", "grep oom_kill /sys/fs/cgroup/memory.events")
await run("timeout", "sleep 30", 2)
# Last: the fork bomb leaves ~255 sleepers holding the pid limit for 20 s.
await run("fork", "python -c \\"import subprocess; [subprocess.Popen(['sleep', '20']) for _ in range(400)]\\"")
""",
    )
    assert r["pids_max"]["stdout"].strip() == "256"
    assert r["mem_max"]["stdout"].strip() == str(4 * 1024**3)
    assert r["fork"]["exit_code"] != 0, r["fork"]
    # Python's BlockingIOError, or runc's own pthread_create failure when the exec itself hits it.
    fork_output = r["fork"]["stdout"] + r["fork"]["stderr"]
    assert "Resource temporarily unavailable" in fork_output, r["fork"]
    assert r["oom"]["exit_code"] != 0
    assert int(r["oom_events"]["stdout"].split()[1]) >= 1, "the kernel OOM-killed it"
    assert r["timeout"]["timed_out"] is True


def test_sandboxd_refuses_overrides_escapes_and_excess_sandboxes():
    sids = [uuid.uuid4() for _ in range(3)]
    r = in_worker(
        sids[0],
        f"""
headers = {{"Authorization": "Bearer " + get_settings().sandboxd_token}}
base = get_settings().sandboxd_url
bad = await http.post(base + "/sandboxes", headers=headers, json={{"topic_id": str(sid), "privileged": True}})
out["override"] = bad.status_code
await c.ensure(sid)
for label, call in [("escape_list", c.list_dir(sid, "../..")),
                    ("escape_read", c.read_file(sid, "%2E%2E/%2E%2E/etc/passwd"))]:
    try:
        await call
        out[label] = "allowed"
    except SandboxError as exc:
        out[label] = str(exc)
await c.write_file(sid, "kept.txt", b"still here")
await c.ensure(uuid.UUID("{sids[1]}"))
await c.ensure(uuid.UUID("{sids[2]}"))
""",
    )
    try:
        assert r["override"] == 422
        assert "400" in r["escape_list"] and "escapes" in r["escape_list"]
        assert "400" in r["escape_read"] and "escapes" in r["escape_read"]
        # At capacity the least recently used idle container was evicted; its volume survives.
        running = [n for n in docker_names("ps").split() if n.startswith("lm-sbx-")]
        assert len(running) <= 2
        assert f"lm-sbx-{sids[2]}" in running
        assert f"lm-sbx-{sids[0]}" not in running
        again = in_worker(
            sids[0],
            """
await c.ensure(sid)
out["kept"] = (await c.read_file(sid, "kept.txt")).decode()
""",
        )
        assert again["kept"] == "still here"
    finally:
        cleanup(*sids)


def test_sandbox_containers_have_the_constraints_applied(sid: uuid.UUID):
    in_worker(sid, "await c.ensure(sid)")
    info = json.loads(
        subprocess.run(
            ["docker", "inspect", f"lm-sbx-{sid}"], check=True, capture_output=True, text=True
        ).stdout
    )[0]
    host = info["HostConfig"]
    assert host["NetworkMode"] == "none"
    assert host["ReadonlyRootfs"] is True
    assert host["CapDrop"] == ["ALL"]
    assert "no-new-privileges:true" in host["SecurityOpt"]
    assert host["PidsLimit"] == 256
    assert host["Memory"] == 4 * 1024**3
    assert host["Privileged"] is False
    assert [m["Destination"] for m in info["Mounts"]] == ["/workspace"]
    assert info["Mounts"][0]["Type"] == "volume"


STAGE_VIA_GATEWAY = """
import asyncio, json, pathlib, uuid, httpx
from muse.modules.artifacts.store import ArtifactStore
from muse.policy.classification import DataClassification
from muse.policy.engine import PolicyEngine
from muse.sandbox.client import SandboxClient
from muse.shared.db import create_engine
from muse.shared.settings import get_settings
from muse.tools.gateway import ToolGateway
from muse.tools.recorder import PostgresActionRecorder
from muse.tools.schema import ExecContext, ToolIntent, ToolServices
from muse.tools.specs import build_registry

async def main():
    settings = get_settings()
    engine = create_engine(settings)
    async with httpx.AsyncClient() as http:
        store = ArtifactStore(engine, pathlib.Path(settings.artifacts_dir))
        services = ToolServices(engine=engine, sandbox=SandboxClient(http, settings), artifacts=store)
        ctx = ExecContext(user_id=uuid.UUID("{uid}"), conversation_id=uuid.UUID("{cid}"))
        gw = ToolGateway(build_registry(), PolicyEngine(), PostgresActionRecorder(engine), services, ctx)
        public = await store.put(user_id=ctx.user_id, conversation_id=ctx.conversation_id, topic_id=None,
                                 kind="file", name="data.csv", data=b"a,b\\n1,2\\n",
                                 classification=DataClassification.PUBLIC)
        private = await store.put(user_id=ctx.user_id, conversation_id=ctx.conversation_id, topic_id=None,
                                  kind="file", name="inbox.html", data=b"<secret/>",
                                  classification=DataClassification.AUTHENTICATED)
        out = {{}}
        for name, args in [("stage", {{"artifact_id": str(public.id)}}),
                           ("stage_auth", {{"artifact_id": str(private.id)}}),
                           ("exec", {{"cmd": "python -c \\"import pandas; print(pandas.read_csv('incoming/data.csv').b.sum())\\""}}),
                           ("pip", {{"name": "requests"}})]:
            tool = "sandbox.stage_package" if name == "pip" else ("sandbox.exec" if name == "exec" else "sandbox.stage")
            out[name] = (await gw.invoke(ToolIntent(tool=tool, args=args))).model_dump(mode="json")
        await SandboxClient(http, settings).destroy_volume(ctx.conversation_id)
    print(json.dumps(out))
    await engine.dispose()

asyncio.run(main())
"""


async def test_tools_go_through_the_gateway_and_stage_only_safe_artifacts():
    async with async_logged_in_client() as client:
        user_id = (await client.get("/api/auth/me")).json()["id"]
        conversation_id = (await client.post("/api/conversations", json={})).json()["id"]
        script = STAGE_VIA_GATEWAY.format(uid=user_id, cid=conversation_id)
        stdout = compose("exec", "-T", "worker", "python", "-c", script).stdout
        r = json.loads(stdout.strip().splitlines()[-1])

    assert r["stage"]["ok"] and r["stage"]["output"]["staged"] == "incoming/data.csv"
    assert not r["stage_auth"]["ok"] and "only with approval" in r["stage_auth"]["error"]
    assert r["exec"]["ok"] and r["exec"]["output"]["stdout"].strip() == "2"
    assert not r["pip"]["ok"] and "no network" in r["pip"]["error"]
    statuses = sql(
        "SELECT string_agg(tool || ':' || status, ',' ORDER BY created_at) FROM actions "
        f"WHERE conversation_id = '{conversation_id}'"
    )
    assert statuses == (
        "sandbox.stage:executed,sandbox.stage:failed,sandbox.exec:executed,"
        "sandbox.stage_package:failed"
    )


async def test_topic_uses_its_own_sandbox_and_cleanup_keeps_only_the_volume():
    if not model_online():
        pytest.skip("local model not online")
    async with async_logged_in_client() as client:
        conversation_id = (await client.post("/api/conversations", json={})).json()["id"]
        await client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={
                "content": "Start one background topic titled 'Calc' with the topic tool. Its "
                "objective: use sandbox_exec to run python and compute 3**50, then report it."
            },
        )
        async with asyncio.timeout(600):
            while True:
                state = (await client.get(f"/api/conversations/{conversation_id}/state")).json()
                topics = state["topics"]
                if topics and topics[0]["status"] in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(3)
        topic = topics[0]
        assert topic["status"] == "completed", topic
        assert "717897987691852588770249" in json.dumps(topic["result"]).replace(",", "")
        executed = [a for a in state["actions"] if a["tool"] == "sandbox.exec"]
        assert executed and all(a["status"] == "executed" for a in executed)

        containers = docker_names("ps", "-a")
        volumes = docker_names("volume", "ls")
        assert f"lm-sbx-{topic['id']}" not in containers, "container destroyed on topic end"
        assert f"lm-ws-{topic['id']}" in volumes, "workspace volume kept"
        cleanup(uuid.UUID(topic["id"]), uuid.UUID(conversation_id))


def docker_names(*command: str) -> str:
    fmt = "{{.Name}}" if command[0] == "volume" else "{{.Names}}"
    return subprocess.run(
        ["docker", *command, "--format", fmt], capture_output=True, text=True, check=True
    ).stdout
