"""Conversation activities: persistence, context loading and realtime fanout.

Every write is idempotent on ids minted by the workflow, so activity retries are safe.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio import activity

from muse.memory.context import render_context, select_history
from muse.modules.conversations.conversations_controller import (
    ConversationsController,
    MessagesController,
)
from muse.modules.memory.memory_controller import ProfileMemoryController, SummariesController
from muse.modules.topics.topics_controller import TopicsController
from muse.modules.topics.topics_schema import TopicView
from muse.realtime.publisher import RealtimePublisher
from muse.workflows.schema import (
    CompactionInput,
    CompactionSource,
    HistoryItem,
    LoadTurnInput,
    PersistedMessage,
    PersistMessageInput,
    ProfileContextInput,
    PublishEventInput,
    SaveSummaryInput,
    TurnContext,
)

TITLE_LENGTH = 60


class ConversationActivities:
    def __init__(self, engine: AsyncEngine, publisher: RealtimePublisher) -> None:
        self._engine = engine
        self._publisher = publisher

    @activity.defn(name="conversation.persist_message")
    async def persist_message(self, request: PersistMessageInput) -> PersistedMessage:
        async with self._engine.begin() as conn:
            conversations = ConversationsController(conn)
            await conversations.lock(request.conversation_id)
            message = await MessagesController(conn).append(
                request.conversation_id, request.role, request.content, request.message_id
            )
            title = request.content[:TITLE_LENGTH] if request.role == "user" else None
            await conversations.touch(request.conversation_id, title_if_empty=title)
        return PersistedMessage(id=message.id, seq=message.seq)

    @activity.defn(name="conversation.load_turn")
    async def load_turn(self, request: LoadTurnInput) -> TurnContext:
        async with self._engine.connect() as conn:
            messages = MessagesController(conn)
            current = await messages.get(request.message_id)
            summary = await SummariesController(conn).latest(request.conversation_id)
            candidates = await messages.between(
                request.conversation_id,
                after_seq=summary[0] if summary else 0,
                before_seq=current.seq,
            )
            # A message queued while the previous turn ran gets a lower seq than that turn's
            # reply. Turns are sequential, so any later assistant message answers an earlier
            # turn and belongs in this turn's history.
            candidates += await messages.replies_after(request.conversation_id, current.seq)
            profile = await ProfileMemoryController(conn).list_for_user(request.user_id)
            topics = await TopicsController(conn).list_for_conversation(
                request.conversation_id, request.user_id
            )
        window = select_history(
            [m.seq for m in candidates],
            [m.content for m in candidates],
            request.token_budget,
            request.history_limit,
        )
        return TurnContext(
            prompt=f"[event] {current.content}" if current.role == "event" else current.content,
            history=[
                HistoryItem(role=candidates[i].role, content=candidates[i].content)
                for i in window.selected
            ],
            context=render_context(
                [(f.key, f.value) for f in profile],
                [(t.title, t.status.value, topic_summary(t)) for t in topics],
                summary[1] if summary else None,
            ),
            compact_up_to=window.compact_up_to,
        )

    @activity.defn(name="conversation.load_compaction")
    async def load_compaction(self, request: CompactionInput) -> CompactionSource:
        async with self._engine.connect() as conn:
            summary = await SummariesController(conn).latest(request.conversation_id)
            after = summary[0] if summary else 0
            older = await MessagesController(conn).between(
                request.conversation_id, after_seq=after, before_seq=request.up_to_seq + 1
            )
        transcript = "\n".join(f"{m.role}: {m.content}" for m in older)
        return CompactionSource(
            previous_summary=summary[1] if summary else None,
            transcript=transcript[-request.max_chars :],
        )

    @activity.defn(name="conversation.save_summary")
    async def save_summary(self, request: SaveSummaryInput) -> None:
        async with self._engine.begin() as conn:
            await SummariesController(conn).save(
                request.conversation_id, request.up_to_seq, request.content
            )

    @activity.defn(name="memory.profile_context")
    async def profile_context(self, request: ProfileContextInput) -> str | None:
        async with self._engine.connect() as conn:
            profile = await ProfileMemoryController(conn).list_for_user(request.user_id)
        return render_context([(f.key, f.value) for f in profile], [], None)

    @activity.defn(name="conversation.publish_event")
    async def publish_event(self, request: PublishEventInput) -> None:
        await self._publisher.publish(request.channel, request.event_type, request.data)


def topic_summary(topic: TopicView) -> str:
    result: Any = topic.result or {}
    report = result.get("report") if isinstance(result, dict) else None
    return str(report.get("summary", "")) if isinstance(report, dict) else ""
