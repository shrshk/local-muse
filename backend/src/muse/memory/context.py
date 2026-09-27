"""Context construction (spec §15): token-budgeted history plus a compact memory block.

Token counts are estimates (~4 characters per token); budgets leave headroom for that.
"""

from dataclasses import dataclass

CHARS_PER_TOKEN = 4
MESSAGE_OVERHEAD_TOKENS = 4


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + MESSAGE_OVERHEAD_TOKENS


@dataclass(frozen=True)
class HistoryWindow:
    selected: list[int]
    """Indexes into the candidate list, oldest first."""
    compact_up_to: int | None
    """Seq of the newest message left out of the window, if any needs summarizing."""


def select_history(
    seqs: list[int], texts: list[str], budget_tokens: int, max_messages: int
) -> HistoryWindow:
    """Newest-first until the budget or message cap is reached. Inputs are oldest first."""
    chosen: list[int] = []
    used = 0
    for i in range(len(texts) - 1, -1, -1):
        cost = estimate_tokens(texts[i])
        if chosen and (used + cost > budget_tokens or len(chosen) >= max_messages):
            break
        chosen.append(i)
        used += cost
    chosen.reverse()
    oldest = chosen[0] if chosen else len(seqs)
    return HistoryWindow(selected=chosen, compact_up_to=seqs[oldest - 1] if oldest > 0 else None)


def render_context(
    profile: list[tuple[str, str]],
    topic_summaries: list[tuple[str, str, str]],
    conversation_summary: str | None,
) -> str | None:
    """A system block for the model. None when there is nothing to say."""
    sections: list[str] = []
    if profile:
        facts = "\n".join(f"- {key}: {value}" for key, value in profile)
        sections.append(f"Known facts about the user (profile memory):\n{facts}")
    if conversation_summary:
        sections.append(f"Summary of earlier conversation:\n{conversation_summary}")
    if topic_summaries:
        lines = "\n".join(
            f"- {title} [{status}]: {summary or 'no summary yet'}"
            for title, status, summary in topic_summaries
        )
        sections.append(f"Background topics in this conversation:\n{lines}")
    return "\n\n".join(sections) if sections else None
