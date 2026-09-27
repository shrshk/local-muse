"""The registered tool set. The only module that imports executors."""

from typing import Any

from muse.policy.classification import (
    Classification,
    DataClassification,
    RiskClass,
    SideEffectClass,
)
from muse.tools.executors import clock, topics
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
        ]
    )
