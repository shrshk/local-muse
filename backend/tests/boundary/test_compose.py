"""Static checks on the rendered Compose config. These guard privilege separation."""

import json
import pathlib
import shutil
import subprocess
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
DOCKER_SOCKET = "/var/run/docker.sock"


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not installed")
    out = subprocess.run(
        [
            "docker", "compose",
            "-f", str(ROOT / "infra/docker-compose.yml"),
            "--env-file", str(ROOT / ".env.example"),
            "config", "--format", "json",
        ],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    rendered: dict[str, Any] = json.loads(out.stdout)
    return rendered


def mounts(service: dict[str, Any]) -> list[dict[str, Any]]:
    return [v for v in service.get("volumes", []) if v.get("type") == "bind"]


def test_only_sandboxd_mounts_the_docker_socket(config: dict[str, Any]):
    holders = {
        name
        for name, svc in config["services"].items()
        if any(m["source"] == DOCKER_SOCKET for m in mounts(svc))
    }
    assert holders == {"sandboxd"}


def test_no_service_mounts_the_host_home(config: dict[str, Any]):
    home = str(pathlib.Path.home())
    for name, svc in config["services"].items():
        for m in mounts(svc):
            if m["source"].startswith(home):
                # Repo config files are fine; anything else under ~ is not.
                assert m["source"].startswith(str(ROOT / "infra")), (name, m["source"])
                assert m.get("read_only"), (name, m["source"])


def test_every_service_has_a_memory_limit(config: dict[str, Any]):
    missing = [name for name, svc in config["services"].items() if not svc.get("mem_limit")]
    assert missing == []


def test_sandbox_control_is_internal_and_only_worker_and_sandboxd_join(config: dict[str, Any]):
    network = next(n for k, n in config["networks"].items() if k == "sandbox-control")
    assert network.get("internal") is True
    members = {
        name
        for name, svc in config["services"].items()
        if "sandbox-control" in svc.get("networks", {})
    }
    assert members == {"worker", "sandboxd"}


def test_sandboxd_has_no_default_network(config: dict[str, Any]):
    assert set(config["services"]["sandboxd"]["networks"]) == {"sandbox-control"}


def test_sandboxd_is_hardened(config: dict[str, Any]):
    svc = config["services"]["sandboxd"]
    assert svc["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in svc["security_opt"]
    assert svc["read_only"] is True


def test_published_ports_bind_loopback_only(config: dict[str, Any]):
    for name, svc in config["services"].items():
        for port in svc.get("ports", []):
            assert port.get("host_ip") == "127.0.0.1", (name, port)
