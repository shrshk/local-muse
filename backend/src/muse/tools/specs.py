"""The registered tool set. The only module that imports executors."""

from typing import Any

from muse.policy.classification import (
    Classification,
    DataClassification,
    RiskClass,
    SideEffectClass,
)
from muse.tools.executors import clock, outbox, profile, sandbox, topics
from muse.tools.registry import ToolRegistry
from muse.tools.schema import ExecContext, RetryPolicy, ToolSpec


def _read_only(_: Any, __: ExecContext) -> Classification:
    return Classification(
        risk=RiskClass.READ_ONLY,
        side_effect=SideEffectClass.NONE,
        data_classification=DataClassification.PUBLIC,
    )


def _local_mutation(_: Any, __: ExecContext) -> Classification:
    return Classification(
        risk=RiskClass.LOCAL_MUTATION,
        side_effect=SideEffectClass.NONE,
        data_classification=DataClassification.PERSONAL,
    )


def _sandbox_write(_: Any, __: ExecContext) -> Classification:
    return Classification(
        risk=RiskClass.LOCAL_MUTATION,
        side_effect=SideEffectClass.LOCAL_FILE_WRITE,
        data_classification=DataClassification.PERSONAL,
    )


def _sandbox_read(_: Any, __: ExecContext) -> Classification:
    return Classification(
        risk=RiskClass.READ_ONLY,
        side_effect=SideEffectClass.NONE,
        data_classification=DataClassification.PERSONAL,
    )


def _message_send(args: Any, _: ExecContext) -> Classification:
    return Classification(
        risk=RiskClass.EXTERNAL_WRITE,
        side_effect=SideEffectClass.MESSAGE_SEND,
        data_classification=DataClassification.PERSONAL,
        destination=str(args.recipient),
    )


def build_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolSpec(
                name="clock.now",
                description="Current date and time in a timezone.",
                args_model=clock.ClockNowArgs,
                classify=_read_only,
                executor=clock.now,
                retry=RetryPolicy(max_attempts=3),
                idempotent=True,
            ),
            ToolSpec(
                name="topic.start",
                description=(
                    "Start a background topic that works on one objective independently and "
                    "reports back when done. Use for longer, separable work. At most 3 at once."
                ),
                args_model=topics.TopicStartArgs,
                classify=_local_mutation,
                executor=topics.start,
            ),
            ToolSpec(
                name="profile.remember",
                description=(
                    "Save a long-lived fact about the user (preferences, constraints, devices, "
                    "standing choices) to profile memory. Never store secrets or passwords."
                ),
                args_model=profile.RememberArgs,
                classify=_local_mutation,
                executor=profile.remember,
                idempotent=True,
            ),
            ToolSpec(
                name="outbox.send",
                description=(
                    "Send a message to someone by email address. Requires the user's approval "
                    "before it is sent."
                ),
                args_model=outbox.SendArgs,
                classify=_message_send,
                executor=outbox.send,
                idempotent=True,
            ),
            ToolSpec(
                name="sandbox.exec",
                description=(
                    "Run a shell command in your private sandbox (Linux, no network, "
                    f"preinstalled: {sandbox.PREINSTALLED}). Files persist in /workspace."
                ),
                args_model=sandbox.ExecArgs,
                classify=_sandbox_write,
                executor=sandbox.exec_cmd,
                timeout_s=sandbox.MAX_EXEC_SECONDS + 30,
            ),
            ToolSpec(
                name="sandbox.write_file",
                description="Write a text file in the sandbox /workspace.",
                args_model=sandbox.WriteFileArgs,
                classify=_sandbox_write,
                executor=sandbox.write_file,
                idempotent=True,
            ),
            ToolSpec(
                name="sandbox.read_file",
                description="Read a text file from the sandbox /workspace.",
                args_model=sandbox.PathArgs,
                classify=_sandbox_read,
                executor=sandbox.read_file,
                idempotent=True,
                retry=RetryPolicy(max_attempts=3),
            ),
            ToolSpec(
                name="sandbox.list",
                description="List a directory in the sandbox /workspace.",
                args_model=sandbox.PathArgs,
                classify=_sandbox_read,
                executor=sandbox.list_dir,
                idempotent=True,
                retry=RetryPolicy(max_attempts=3),
            ),
            ToolSpec(
                name="sandbox.stage",
                description="Copy an artifact you obtained earlier into /workspace/incoming/.",
                args_model=sandbox.StageArgs,
                classify=_sandbox_write,
                executor=sandbox.stage,
            ),
            ToolSpec(
                name="sandbox.stage_package",
                description="Install a package into the sandbox (not available in this version).",
                args_model=sandbox.StagePackageArgs,
                classify=_sandbox_write,
                executor=sandbox.stage_package,
            ),
        ]
    )
