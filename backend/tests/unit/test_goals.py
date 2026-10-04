import datetime as dt
import uuid
from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError

from muse.activities.goals import RecordObservationInput, normalize, should_notify
from muse.agents.goal_checker import NO_NESTED_WORK
from muse.agents.toolset import build_toolset
from muse.modules.goals.goals_schema import GoalTiming
from muse.tools.errors import ToolExecutionError
from muse.tools.executors.goals import GoalCreateArgs, create
from muse.tools.specs import build_registry
from tests.fakes import NO_SERVICES, make_ctx


@pytest.mark.parametrize(
    "timing",
    [{}, {"after_minutes": 5, "every_minutes": 5}, {"after_minutes": -1}, {"every_minutes": 0}],
)
def test_timing_needs_exactly_one_valid_choice(timing: dict[str, Any]):
    with pytest.raises(ValidationError):
        GoalTiming.model_validate(timing)


def test_timing_kinds_and_first_run():
    now = dt.datetime(2026, 9, 27, 12, 0, tzinfo=dt.UTC)
    tomorrow = GoalTiming(after_minutes=1440)
    assert tomorrow.kind == "once"
    assert tomorrow.first_run(now) == now + dt.timedelta(days=1)
    recurring = GoalTiming(every_minutes=30)
    assert recurring.kind == "recurring"
    assert recurring.first_run(now) == now, "recurring goals check right away"
    now_once = GoalTiming(after_minutes=0)
    assert now_once.kind == "once" and now_once.first_run(now) == now
    at = dt.datetime(2026, 9, 28, 9, 0, tzinfo=dt.UTC)
    assert GoalTiming(at=at).first_run(now) == at


def test_naive_times_are_rejected():
    with pytest.raises(ValidationError):
        GoalTiming.model_validate({"at": "2026-09-28T09:00:00"})


def goal(**overrides: Any) -> dict[str, Any]:
    base = {"kind": "recurring", "condition": None, "run_count": 1, "last_value": "Alpha"}
    return {**base, "last_condition": None, **overrides}


def seen(value: str, condition: bool | None = None) -> RecordObservationInput:
    return RecordObservationInput(
        goal_id=uuid.uuid4(), value=value, condition_met=condition, summary="s"
    )


def test_one_shot_goals_always_report():
    assert should_notify(goal(kind="once", run_count=0), seen("anything"))


def test_first_recurring_run_is_only_a_baseline():
    assert not should_notify(goal(run_count=0, last_value=None), seen("Alpha"))


def test_recurring_goals_notify_only_on_change():
    assert not should_notify(goal(), seen("alpha."))  # same value, different case/punctuation
    assert should_notify(goal(), seen("Beta"))


def test_conditions_notify_on_the_flip_to_true_only():
    cond = {"condition": "price below 100"}
    assert should_notify(goal(**cond, last_condition=False), seen("95", True))
    assert should_notify(goal(**cond, run_count=0, last_condition=None), seen("95", True))
    assert not should_notify(goal(**cond, last_condition=True), seen("94", True))
    assert not should_notify(goal(**cond, last_condition=False), seen("120", False))


def test_normalize():
    assert normalize("  Beta  Release. ") == "beta release"


ARGS = GoalCreateArgs(title="t", objective="o", after_minutes=10)


async def test_goals_come_only_from_user_turns_outside_topics():
    with pytest.raises(ToolExecutionError, match="background"):
        await create(ARGS, make_ctx(topic_id=uuid.uuid4()), NO_SERVICES)
    with pytest.raises(ToolExecutionError, match="user message"):
        await create(ARGS, replace(make_ctx(), trigger="event"), NO_SERVICES)


def test_goal_checker_cannot_start_topics_or_goals():
    tools = {t.name for t in build_toolset(build_registry(), NO_NESTED_WORK).tools.values()}
    assert "goal_create" not in tools and "topic_start" not in tools
    assert "clock_now" in tools and "browser_snapshot" in tools
