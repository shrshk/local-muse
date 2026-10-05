"""Interruption budget: which notifications earn a push. Trusted code only.

Every notification lands in the in-app feed. A push is the interruption, and it is rationed per
kind: a level (all / important / none) and a daily cap. Approvals always push; they block work.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Level(StrEnum):
    ALL = "all"
    IMPORTANT = "important"
    NONE = "none"


class Importance(StrEnum):
    NORMAL = "normal"
    HIGH = "high"


ALWAYS_PUSH = frozenset({"approval", "test"})
# Ordered from loudest to quietest, for "more" / "less" feedback.
LEVELS = (Level.ALL, Level.IMPORTANT, Level.NONE)
MAX_DAILY_CAP = 50


class Preference(BaseModel):
    kind: str
    level: Level
    daily_cap: int = Field(ge=0, le=MAX_DAILY_CAP)


DEFAULTS: dict[str, Preference] = {
    "goal": Preference(kind="goal", level=Level.ALL, daily_cap=10),
    "idea": Preference(kind="idea", level=Level.IMPORTANT, daily_cap=3),
}
FALLBACK = Preference(kind="other", level=Level.IMPORTANT, daily_cap=5)

Feedback = Literal["more", "less", "none"]


def preference_for(kind: str, stored: Preference | None) -> Preference:
    if stored is not None:
        return stored
    default = DEFAULTS.get(kind, FALLBACK)
    return default.model_copy(update={"kind": kind})


def should_push(kind: str, importance: Importance, pref: Preference, pushed_today: int) -> bool:
    if kind in ALWAYS_PUSH:
        return True
    if pref.level is Level.NONE:
        return False
    if pref.level is Level.IMPORTANT and importance is not Importance.HIGH:
        return False
    return pushed_today < pref.daily_cap


def apply_feedback(pref: Preference, feedback: Feedback) -> Preference:
    index = LEVELS.index(pref.level)
    if feedback == "none":
        level = Level.NONE
    elif feedback == "more":
        level = LEVELS[max(index - 1, 0)]
    else:
        level = LEVELS[min(index + 1, len(LEVELS) - 1)]
    return pref.model_copy(update={"level": level})
