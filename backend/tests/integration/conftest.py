"""Integration tests run against the live Compose stack. Start it with `make up-detached`."""

import os
import pathlib
import secrets
import subprocess
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
WEB_URL = os.getenv("LOCAL_MUSE_URL", "http://localhost:8080")
COMPOSE = [
    "docker", "compose",
    "-f", str(ROOT / "infra/docker-compose.yml"),
    "--env-file", str(ROOT / ".env"),
]  # fmt: skip


def compose(
    *args: str, check: bool = True, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*COMPOSE, *args], check=check, capture_output=True, text=True, input=stdin
    )


def container_id(service: str) -> str:
    return compose("ps", "-q", service).stdout.strip()


def sql(query: str) -> str:
    return compose(
        "exec", "-T", "postgres", "sh", "-c", f'psql -U "$POSTGRES_USER" muse -tA -c "{query}"'
    ).stdout.strip()


def create_user() -> tuple[str, str]:
    username = f"itest-{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(18)
    compose(
        "exec", "-T", "backend", "python", "-m", "muse.cli", "create-user",
        "--username", username, "--password-stdin",
        stdin=password + "\n",
    )  # fmt: skip
    return username, password


@contextmanager
def logged_in_client() -> Iterator[httpx.Client]:
    username, password = create_user()
    with httpx.Client(base_url=WEB_URL, timeout=660) as client:
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        response.raise_for_status()
        yield client


@asynccontextmanager
async def async_logged_in_client() -> AsyncIterator[httpx.AsyncClient]:
    username, password = create_user()
    async with httpx.AsyncClient(base_url=WEB_URL, timeout=660) as client:
        response = await client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        response.raise_for_status()
        yield client


def model_online() -> bool:
    with logged_in_client() as c:
        return bool(c.get("/api/models/health").json()["status"] == "online")


@pytest.fixture(scope="session", autouse=True)
def stack_up() -> None:
    try:
        httpx.get(f"{WEB_URL}/api/health/live", timeout=2).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"stack not reachable at {WEB_URL}; run 'make up-detached' ({exc})")


@pytest.fixture(scope="session")
def client() -> Iterator[httpx.Client]:
    with logged_in_client() as c:
        yield c
