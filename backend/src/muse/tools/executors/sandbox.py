"""sandbox.*: run code and handle files in the topic's no-network sandbox (via sandboxd).

The sandbox is keyed by topic (or by conversation for the coordinator). Its container is
ephemeral; its /workspace volume persists until explicitly destroyed.
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from muse.modules.artifacts.artifacts_controller import SandboxesController
from muse.policy.classification import DataClassification
from muse.sandbox.client import SandboxClient, SandboxError
from muse.tools.errors import ToolExecutionError
from muse.tools.schema import ExecContext, ToolServices

MAX_EXEC_SECONDS = 120
MAX_READ_CHARS = 64 * 1024
PREINSTALLED = (
    "python3.12 (numpy, pandas, polars, matplotlib, pyarrow, openpyxl, bs4, lxml), "
    "node, jq, ripgrep, git"
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecArgs(Strict):
    cmd: str = Field(min_length=1, max_length=10_000, description="Shell command (sh -c)")
    timeout_s: int = Field(default=60, ge=1, le=MAX_EXEC_SECONDS)
    cwd: str = Field(default=".", description="Directory relative to /workspace")


class WriteFileArgs(Strict):
    path: str = Field(min_length=1, max_length=500, description="Path relative to /workspace")
    content: str = Field(max_length=1_000_000)


class PathArgs(Strict):
    path: str = Field(default=".", max_length=500, description="Path relative to /workspace")


class StageArgs(Strict):
    artifact_id: uuid.UUID


class StagePackageArgs(Strict):
    name: str
    version: str | None = None


def sandbox_id(ctx: ExecContext) -> uuid.UUID:
    return ctx.topic_id or ctx.conversation_id


async def _ready(ctx: ExecContext, services: ToolServices) -> tuple[SandboxClient, uuid.UUID]:
    if services.sandbox is None:
        raise ToolExecutionError("no sandbox available here")
    sid = sandbox_id(ctx)
    try:
        info = await services.sandbox.ensure(sid)
    except SandboxError as exc:
        raise ToolExecutionError(str(exc)) from exc
    if info.get("status") == "created":
        async with services.engine.begin() as conn:
            await SandboxesController(conn).record(
                sid, ctx.conversation_id, ctx.topic_id, f"lm-ws-{sid}", "running"
            )
    return services.sandbox, sid


async def exec_cmd(args: ExecArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    client, sid = await _ready(ctx, services)
    try:
        result = await client.exec(sid, args.cmd, args.timeout_s, args.cwd)
    except SandboxError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return {k: result[k] for k in ("exit_code", "stdout", "stderr", "truncated", "timed_out")}


async def write_file(args: WriteFileArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    client, sid = await _ready(ctx, services)
    try:
        await client.write_file(sid, args.path, args.content.encode())
    except SandboxError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return {"written": args.path, "bytes": len(args.content.encode())}


async def read_file(args: PathArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    client, sid = await _ready(ctx, services)
    try:
        data = await client.read_file(sid, args.path)
    except SandboxError as exc:
        raise ToolExecutionError(str(exc)) from exc
    text = data.decode(errors="replace")
    return {
        "path": args.path,
        "content": text[:MAX_READ_CHARS],
        "truncated": len(text) > MAX_READ_CHARS,
    }


async def list_dir(args: PathArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    client, sid = await _ready(ctx, services)
    try:
        entries = await client.list_dir(sid, args.path)
    except SandboxError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return {"path": args.path, "entries": entries}  # type: ignore[dict-item]


async def stage(args: StageArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    """Copy an artifact this conversation obtained through a trusted tool into incoming/."""
    if services.artifacts is None:
        raise ToolExecutionError("artifacts are not available here")
    found = await services.artifacts.get(args.artifact_id, ctx.conversation_id)
    if found is None:
        raise ToolExecutionError("no such artifact in this conversation")
    artifact, data = found
    if artifact.classification in (DataClassification.AUTHENTICATED, DataClassification.SECRET):
        # Phase 8 turns AUTHENTICATED into an approval request; until then it is refused.
        raise ToolExecutionError("authenticated content cannot be copied into a sandbox")
    client, sid = await _ready(ctx, services)
    try:
        path = await client.stage(sid, artifact.name, data)
    except SandboxError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return {"staged": path, "bytes": artifact.size}


async def stage_package(
    args: StagePackageArgs, ctx: ExecContext, services: ToolServices
) -> JsonValue:
    raise ToolExecutionError(
        f"installing packages is not available: the sandbox has no network. "
        f"Preinstalled: {PREINSTALLED}."
    )
