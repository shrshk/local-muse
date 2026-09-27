"""Conversation reads, and message sends that hand off to ConversationWorkflow."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio.client import (
    WithStartWorkflowOperation,
    WorkflowUpdateFailedError,
)
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError, RPCStatusCode

from muse.modules.actions.actions_controller import ActionsController
from muse.modules.actions.actions_schema import ActionView
from muse.modules.approvals.approvals_controller import ApprovalsController
from muse.modules.browser.browser_controller import BrowserSessionsController
from muse.modules.conversations.conversations_controller import (
    ConversationsController,
    MessagesController,
)
from muse.modules.conversations.conversations_schema import (
    ConversationStateView,
    ConversationView,
    MessageView,
)
from muse.modules.realtime.realtime_controller import RealtimeSeqController
from muse.modules.topics.topics_controller import TopicsController
from muse.realtime.publisher import conversation_channel
from muse.shared.logger import get_logger
from muse.shared.settings import Settings
from muse.shared.temporal import TemporalClientProvider
from muse.workflows.schema import (
    ConversationState,
    ConversationStatus,
    SendMessageAck,
    SendMessageInput,
)

logger = get_logger(__name__)

# Referenced by name so the API process never imports workflow or agent code.
WORKFLOW_TYPE = "ConversationWorkflow"


class ConversationNotFound(Exception):
    pass


class MessageRejected(Exception):
    pass


class WorkflowUnavailable(Exception):
    pass


def workflow_id(conversation_id: uuid.UUID) -> str:
    return f"conv-{conversation_id}"


class ConversationsHandler:
    def __init__(
        self, engine: AsyncEngine, temporal: TemporalClientProvider, settings: Settings
    ) -> None:
        self._engine = engine
        self._temporal = temporal
        self._settings = settings

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

    async def require_owner(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
        async with self._engine.connect() as conn:
            await self._require(ConversationsController(conn), conversation_id, user_id)

    async def state(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> ConversationStateView:
        async with self._engine.connect() as conn:
            conversation = await self._require(
                ConversationsController(conn), conversation_id, user_id
            )
            # Seq first: anything published after this read is either in the rows below or
            # arrives as an event with a higher seq.
            seq = await RealtimeSeqController(conn).current(conversation_channel(conversation_id))
            messages = await MessagesController(conn).list_for_conversation(conversation_id)
            actions = await ActionsController(conn).list_for_conversation(conversation_id, user_id)
            topics = await TopicsController(conn).list_for_conversation(conversation_id, user_id)
            approvals = await ApprovalsController(conn).list_for_user(
                user_id, conversation_id=conversation_id
            )
            browsers = await BrowserSessionsController(conn).list_for_conversation(
                conversation_id, user_id
            )
        return ConversationStateView(
            conversation=conversation,
            seq=seq,
            messages=messages,
            actions=actions,
            topics=topics,
            approvals=approvals,
            browser_sessions=browsers,
            status=await self._status(conversation_id),
        )

    async def send_message(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, content: str
    ) -> SendMessageAck:
        await self.require_owner(conversation_id, user_id)
        start: WithStartWorkflowOperation[Any, None] = WithStartWorkflowOperation(
            WORKFLOW_TYPE,
            ConversationState(
                conversation_id=conversation_id,
                user_id=user_id,
                history_limit=self._settings.chat_history_messages,
                history_token_budget=self._settings.history_token_budget,
                approval_timeout_s=self._settings.approval_timeout_s,
            ),
            id=workflow_id(conversation_id),
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            task_queue=self._settings.task_queue_main,
            result_type=type(None),
        )
        try:
            client = await self._temporal.get()
            ack: SendMessageAck = await client.execute_update_with_start_workflow(
                "send_message",
                SendMessageInput(content=content),
                start_workflow_operation=start,
                result_type=SendMessageAck,
            )
            return ack
        except WorkflowUpdateFailedError as exc:
            raise MessageRejected(str(exc.cause)) from exc
        except (RPCError, RuntimeError) as exc:
            logger.exception("workflow_send_failed", conversation_id=str(conversation_id))
            raise WorkflowUnavailable(type(exc).__name__) from exc

    async def _status(self, conversation_id: uuid.UUID) -> ConversationStatus:
        try:
            client = await self._temporal.get()
            handle = client.get_workflow_handle(workflow_id(conversation_id))
            status: ConversationStatus = await handle.query(
                "status", result_type=ConversationStatus
            )
            return status
        except RPCError as exc:
            if exc.status is not RPCStatusCode.NOT_FOUND:
                logger.warning("workflow_status_unavailable", error=exc.status.name)
            return ConversationStatus()

    async def _require(
        self, controller: ConversationsController, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> ConversationView:
        conversation = await controller.get(conversation_id, user_id)
        if conversation is None:
            raise ConversationNotFound(str(conversation_id))
        return conversation
