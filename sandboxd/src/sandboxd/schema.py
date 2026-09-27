"""Request and response shapes. Unknown fields are rejected, so no constraint can be passed in."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from sandboxd.constraints import MAX_EXEC_SECONDS


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSandbox(Strict):
    topic_id: uuid.UUID


class SandboxView(BaseModel):
    sandbox_id: uuid.UUID
    status: str


class ExecRequest(Strict):
    cmd: str = Field(min_length=1, max_length=10_000)
    timeout_s: int = Field(default=60, ge=1, le=MAX_EXEC_SECONDS)
    cwd: str = "."


class ExecResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool
    timed_out: bool


class DirEntry(BaseModel):
    name: str
    kind: str
    size: int


class StageRequest(Strict):
    filename: str = Field(min_length=1, max_length=200)
    content_b64: str
