import uuid

import pytest

from muse.activities.topics import merge_outcome
from muse.agents.toolset import build_toolset
from muse.agents.topic_worker import NO_TOPIC_TOOLS
from muse.modules.topics.topics_schema import TopicMemoryDocument
from muse.tools.errors import ToolExecutionError
from muse.tools.executors.topics import TopicStartArgs, start
from muse.tools.specs import build_registry
from muse.workflows.conversation import as_prompt, to_model_history
from muse.workflows.schema import FinishTopicInput, HistoryItem
from tests.fakes import NO_SERVICES, make_ctx


async def test_a_topic_cannot_start_a_topic():
    args = TopicStartArgs(title="t", objective="o")
    with pytest.raises(ToolExecutionError, match="cannot start"):
        await start(args, make_ctx(topic_id=uuid.uuid4()), NO_SERVICES)


def test_topic_worker_toolset_has_no_topic_tool():
    registry = build_registry()
    coordinator_tools = {t.name for t in build_toolset(registry).tools.values()}
    worker_tools = {t.name for t in build_toolset(registry, NO_TOPIC_TOOLS).tools.values()}
    assert "topic_start" in coordinator_tools
    assert "topic_start" not in worker_tools
    assert "clock_now" in worker_tools


def test_completed_outcome_fills_memory_from_the_report():
    doc = TopicMemoryDocument(objective="find x", decisions=["earlier"])
    merged = merge_outcome(
        doc,
        FinishTopicInput(
            topic_id=uuid.uuid4(),
            status="completed",
            report={"summary": "found x", "decisions": ["d1"], "next_actions": ["n1"]},
        ),
    )
    assert merged.summary == "found x"
    assert merged.decisions == ["earlier", "d1"]
    assert merged.next_actions == ["n1"]
    assert merged.objective == "find x"
    assert doc.summary == "", "the input document is not mutated"


def test_cancelled_and_failed_outcomes_are_noted():
    doc = TopicMemoryDocument()
    cancelled = merge_outcome(doc, FinishTopicInput(topic_id=uuid.uuid4(), status="cancelled"))
    failed = merge_outcome(
        doc, FinishTopicInput(topic_id=uuid.uuid4(), status="failed", error="ModelAPIError")
    )
    assert cancelled.unfinished_work == ["Cancelled before completion."]
    assert failed.failed_approaches == ["Run failed: ModelAPIError"]


def test_memory_document_rejects_unknown_fields():
    with pytest.raises(ValueError):
        TopicMemoryDocument.model_validate({"summary": "", "api_key": "sk-..."})


def test_event_messages_reach_the_model_as_marked_user_prompts():
    item = HistoryItem(role="event", content='Topic "x" completed.')
    assert as_prompt(item) == '[event] Topic "x" completed.'
    assert len(to_model_history([item])) == 1


async def test_relaying_an_event_cannot_start_topics():
    ctx = make_ctx()
    event_ctx = type(ctx)(user_id=ctx.user_id, conversation_id=ctx.conversation_id, trigger="event")
    with pytest.raises(ToolExecutionError, match="user message"):
        await start(TopicStartArgs(title="t", objective="o"), event_ctx, NO_SERVICES)
