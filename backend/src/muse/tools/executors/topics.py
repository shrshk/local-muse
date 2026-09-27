"""topic.start: records a background topic. The conversation workflow starts it after the turn.

The executor never starts a workflow itself; it only writes a pending row the trusted workflow
code acts on. Depth is 1: a topic cannot start topics. Only a user message can start one, so
relaying a topic result never re-starts work mentioned earlier in the history.
"""

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from muse.modules.conversations.conversations_controller import ConversationsController
from muse.modules.topics.topics_controller import TopicMemoryController, TopicsController
from muse.modules.topics.topics_schema import TopicMemoryDocument
from muse.tools.errors import ToolExecutionError
from muse.tools.schema import ExecContext, ToolServices

MAX_ACTIVE_TOPICS = 3


class TopicStartArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80, description="Short name for the topic")
    objective: str = Field(
        min_length=1, max_length=2000, description="What the background worker should achieve"
    )


async def start(args: TopicStartArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    if ctx.topic_id is not None:
        raise ToolExecutionError("topics cannot start other topics")
    if ctx.trigger != "user":
        raise ToolExecutionError("topics can only be started in reply to a user message")
    async with services.engine.begin() as conn:
        # The conversation lock serializes concurrent starts, so the count cannot race.
        await ConversationsController(conn).lock(ctx.conversation_id)
        topics = TopicsController(conn)
        if await topics.count_active(ctx.conversation_id) >= MAX_ACTIVE_TOPICS:
            raise ToolExecutionError(f"at most {MAX_ACTIVE_TOPICS} topics can run at once")
        topic = await topics.create(ctx.conversation_id, ctx.user_id, args.title, args.objective)
        await TopicMemoryController(conn).create(
            topic.id, TopicMemoryDocument(objective=args.objective)
        )
    return {"topic_id": str(topic.id), "title": topic.title, "status": "started"}
