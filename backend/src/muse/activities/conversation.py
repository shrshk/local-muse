"""Conversation activities: persistence and realtime fanout for ConversationWorkflow.

Every write is idempotent on ids minted by the workflow, so activity retries are safe.
"""

from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio import activity

from muse.modules.conversations.conversations_controller import (
    ConversationsController,
    MessagesController,
)
from muse.realtime.publisher import RealtimePublisher
from muse.workflows.schema import (
    HistoryItem,
    LoadTurnInput,
    PersistedMessage,
    PersistMessageInput,
    PublishEventInput,
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
            history = await messages.recent(
                request.conversation_id, request.history_limit, before_seq=current.seq
            )
        return TurnContext(
            prompt=current.content,
            history=[HistoryItem(role=m.role, content=m.content) for m in history],
        )

    @activity.defn(name="conversation.publish_event")
    async def publish_event(self, request: PublishEventInput) -> None:
        await self._publisher.publish(request.channel, request.event_type, request.data)
