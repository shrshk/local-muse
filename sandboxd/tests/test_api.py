from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from sandboxd.main import create_app
from sandboxd.settings import Settings

TOKEN = "t" * 32


class FakeEngine:
    def __init__(self, reachable: bool) -> None:
        self.reachable = reachable

    async def ping(self) -> bool:
        return self.reachable


def make_client(reachable: bool = True) -> TestClient:
    app = create_app(Settings(sandboxd_token=TOKEN), FakeEngine(reachable))  # type: ignore[arg-type]
    return TestClient(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with make_client() as c:
        yield c


def test_health_requires_a_token(client: TestClient):
    assert client.get("/health").status_code == 401


def test_wrong_token_is_rejected(client: TestClient):
    response = client.get("/health", headers={"Authorization": "Bearer " + "x" * 32})
    assert response.status_code == 401


def test_health_reports_docker(client: TestClient):
    response = client.get("/health", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.json()["docker"] == "ok"


def test_health_reports_unreachable_docker():
    with make_client(reachable=False) as c:
        body = c.get("/health", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert body["docker"] == "unreachable"


def test_short_token_is_refused_at_startup():
    with pytest.raises(ValueError, match="at least 32"):
        Settings(sandboxd_token="short")
