import pytest

from muse.memory.context import estimate_tokens, render_context, select_history
from muse.memory.secrets import looks_like_secret
from muse.modules.memory.memory_handler import InvalidFact, validate_fact
from muse.worker.__main__ import model_activities


def test_window_takes_newest_messages_within_budget():
    texts = ["a" * 400, "b" * 400, "c" * 400]  # ~104 tokens each
    window = select_history([1, 2, 3], texts, budget_tokens=250, max_messages=20)
    assert window.selected == [1, 2]
    assert window.compact_up_to == 1


def test_window_respects_the_message_cap():
    window = select_history([1, 2, 3, 4], ["x"] * 4, budget_tokens=10_000, max_messages=2)
    assert window.selected == [2, 3]
    assert window.compact_up_to == 2


def test_everything_fits_means_nothing_to_compact():
    window = select_history([5, 6], ["hi", "there"], budget_tokens=10_000, max_messages=20)
    assert window.selected == [0, 1]
    assert window.compact_up_to is None


def test_one_oversized_message_is_still_kept():
    window = select_history([1, 2], ["a", "z" * 100_000], budget_tokens=100, max_messages=20)
    assert window.selected == [1]
    assert window.compact_up_to == 1


def test_estimate_is_roughly_four_chars_per_token():
    assert estimate_tokens("x" * 400) == 104


def test_context_block_lists_profile_summary_and_topics():
    block = render_context(
        [("home_city", "Austin")], [("Tokyo", "completed", "It is 3pm")], "Talked about travel."
    )
    assert block is not None
    assert "home_city: Austin" in block
    assert "Talked about travel." in block
    assert "Tokyo [completed]: It is 3pm" in block
    assert render_context([], [], None) is None


@pytest.mark.parametrize(
    "value",
    [
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
        "AKIAABCDEFGHIJKLMNOP",
        "ghp_abcdefghijklmnopqrstuvwxyz123456",
        "my password: hunter2",
        "api_key=abc123",
        "-----BEGIN RSA PRIVATE KEY-----",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvd25lciJ9.c2lnbmF0dXJlX2hlcmU",
    ],
)
def test_secrets_are_detected(value: str):
    assert looks_like_secret(value)
    with pytest.raises(InvalidFact):
        validate_fact("note", value)


@pytest.mark.parametrize("value", ["Prefers metric units", "Lives in Austin, TX", "Uses a Pixel 9"])
def test_ordinary_facts_pass(value: str):
    assert not looks_like_secret(value)
    validate_fact("some_key", value)


def test_fact_keys_are_constrained():
    with pytest.raises(InvalidFact):
        validate_fact("Has Spaces", "x")


def test_model_worker_serves_every_agent():
    names = {getattr(a, "__temporal_activity_definition").name for a in model_activities()}
    for agent in ("coordinator", "topic_worker", "summarizer"):
        assert any(n.startswith(f"agent__{agent}__model_request") for n in names), agent
