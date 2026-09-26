"""Conversation CRUD and the non-durable chat turn (Phase 2; Temporal takes over in Phase 3)."""

import uuid

from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from sqlalchemy.ext.asyncio import AsyncEngine

from muse.agents.coordinator import Coordinator
from muse.agents.deps import AgentDeps
from muse.modules.actions.actions_controller import ActionsController
from muse.modules.actions.actions_schema import ActionView
from muse.modules.conversations.conversations_controller import (
    ConversationsController,
    MessagesController,
)
from muse.modules.conversations.conversations_schema import (
    ConversationView,
    MessageView,
    ToolCallView,
    TurnResult,
)
from muse.policy.engine import PolicyEngine
from muse.shared.logger import get_logger
from muse.tools.gateway import ToolGateway
from muse.tools.recorder import ActionRecorder
from muse.tools.registry import ToolRegistry
from muse.tools.schema import ExecContext

logger = get_logger(__name__)

TITLE_LENGTH = 60


class ConversationNotFound(Exception):
    pass


class ModelUnavailable(Exception):
    pass


class ConversationsHandler:
    def __init__(
        self,
        engine: AsyncEngine,
        coordinator: Coordinator,
        registry: ToolRegistry,
        policy: PolicyEngine,
        recorder: ActionRecorder,
        history_limit: int,
    ) -> None:
        self._engine = engine
        self._coordinator = coordinator
        self._registry = registry
        self._policy = policy
        self._recorder = recorder
        self._history_limit = history_limit

    async def create(self, user_id: uuid.UUID, title: str | None) -> ConversationView:
        async with self._engine.begin() as conn:
            return await ConversationsController(conn).create(user_id, title)

    async def list_for_user(self, user_id: uuid.UUID) -> list[ConversationView]:
        async with self._engine.connect() as conn:
            return await ConversationsController(conn).list_for_user(user_id)

    async def messages(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> list[MessageView]:
        async with self._engine.connect() as conn:
            await self._require(ConversationsController(conn), conversation_id, user_id)
            return await MessagesController(conn).list_for_conversation(conversation_id)

    async def actions(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> list[ActionView]:
        async with self._engine.connect() as conn:
            await self._require(ConversationsController(conn), conversation_id, user_id)
            return await ActionsController(conn).list_for_conversation(conversation_id, user_id)

    async def send_message(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, content: str
    ) -> TurnResult:
        async with self._engine.begin() as conn:
            conversations = ConversationsController(conn)
            await self._require(conversations, conversation_id, user_id, for_update=True)
            user_message = await MessagesController(conn).append(conversation_id, "user", content)
            history = await MessagesController(conn).recent(
                conversation_id, self._history_limit, before_seq=user_message.seq
            )
            await conversations.touch(conversation_id, title_if_empty=content[:TITLE_LENGTH])

        ctx = ExecContext(user_id=user_id, conversation_id=conversation_id)
        gateway = ToolGateway(self._registry, self._policy, self._recorder, ctx)
        try:
            reply = await self._coordinator.reply(
                content, _to_model_history(history), AgentDeps(ctx=ctx, tools=gateway)
            )
        except AgentRunError as exc:
            logger.exception("agent_run_failed", conversation_id=str(conversation_id))
            raise ModelUnavailable(type(exc).__name__) from exc

        async with self._engine.begin() as conn:
            await ConversationsController(conn).get(conversation_id, user_id, for_update=True)
            assistant_message = await MessagesController(conn).append(
                conversation_id, "assistant", reply
            )
            await ConversationsController(conn).touch(conversation_id)

        return TurnResult(
            user_message=user_message,
            assistant_message=assistant_message,
            tool_calls=[
                ToolCallView(
                    action_id=p.action_id,
                    tool=p.tool,
                    args=p.args,
                    decision=kind.value,
                    ok=result.ok,
                    output=result.output,
                    error=result.error,
                )
                for p, kind, result in gateway.proposals
            ],
        )

    async def _require(
        self,
        controller: ConversationsController,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> ConversationView:
        conversation = await controller.get(conversation_id, user_id, for_update=for_update)
        if conversation is None:
            raise ConversationNotFound(str(conversation_id))
        return conversation


def _to_model_history(history: list[MessageView]) -> list[ModelMessage]:
    out: list[ModelMessage] = []
    for m in history:
        if m.role == "user":
            out.append(ModelRequest(parts=[UserPromptPart(content=m.content)]))
        else:
            out.append(ModelResponse(parts=[TextPart(content=m.content)]))
    return out
