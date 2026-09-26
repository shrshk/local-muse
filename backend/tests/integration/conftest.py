"""Integration tests run against the live Compose stack. Start it with `make up-detached`."""

import os
import pathlib
import subprocess

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
WEB_URL = os.getenv("LOCAL_MUSE_URL", "http://localhost:8080")
COMPOSE = [
    "docker",
    "compose",
    "-f",
    str(ROOT / "infra/docker-compose.yml"),
    "--env-file",
    str(ROOT / ".env"),
]


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*COMPOSE, *args], check=check, capture_output=True, text=True)


def container_id(service: str) -> str:
    return compose("ps", "-q", service).stdout.strip()


@pytest.fixture(scope="session", autouse=True)
def stack_up() -> None:
    try:
        httpx.get(f"{WEB_URL}/api/health/live", timeout=2).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"stack not reachable at {WEB_URL}; run 'make up-detached' ({exc})")
