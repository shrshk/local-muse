import datetime as dt
import uuid

import pytest

from muse.modules.artifacts.artifacts_schema import ArtifactView
from muse.policy.classification import DataClassification
from muse.tools.errors import ToolExecutionError
from muse.tools.executors import sandbox
from muse.tools.schema import ToolServices
from muse.tools.specs import build_registry
from tests.fakes import NO_SERVICES, make_ctx


def test_sandbox_is_keyed_by_topic_then_conversation():
    ctx = make_ctx()
    assert sandbox.sandbox_id(ctx) == ctx.conversation_id
    topic = uuid.uuid4()
    assert sandbox.sandbox_id(make_ctx(topic_id=topic)) == topic


async def test_package_installs_are_refused_with_a_useful_message():
    with pytest.raises(ToolExecutionError, match="no network"):
        await sandbox.stage_package(
            sandbox.StagePackageArgs(name="requests"), make_ctx(), NO_SERVICES
        )


class FakeArtifacts:
    def __init__(self, classification: DataClassification) -> None:
        self.classification = classification

    async def get(
        self, artifact_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> tuple[ArtifactView, bytes]:
        view = ArtifactView(
            id=artifact_id,
            conversation_id=conversation_id,
            topic_id=None,
            kind="file",
            name="page.html",
            size=4,
            sha256="x",
            classification=self.classification,
            created_at=dt.datetime.now(dt.UTC),
        )
        return view, b"data"


@pytest.mark.parametrize(
    "classification", [DataClassification.AUTHENTICATED, DataClassification.SECRET]
)
async def test_authenticated_artifacts_never_reach_a_sandbox(classification: DataClassification):
    services = ToolServices(engine=None, artifacts=FakeArtifacts(classification))  # type: ignore[arg-type]
    with pytest.raises(ToolExecutionError, match="authenticated"):
        await sandbox.stage(sandbox.StageArgs(artifact_id=uuid.uuid4()), make_ctx(), services)


def test_sandbox_tools_are_registered_with_bounded_exec_time():
    registry = build_registry()
    spec = registry.get("sandbox.exec")
    assert spec is not None
    assert spec.timeout_s > sandbox.MAX_EXEC_SECONDS
    assert not spec.idempotent, "exec has side effects; it is never blindly retried"
    for name in ("sandbox.write_file", "sandbox.read_file", "sandbox.list", "sandbox.stage"):
        assert registry.get(name) is not None


def test_exec_args_bound_the_timeout():
    with pytest.raises(ValueError):
        sandbox.ExecArgs(cmd="sleep 1", timeout_s=10_000)
