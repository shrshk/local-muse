import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from muse.api.deps import conversations_handler, current_user
from muse.modules.actions.actions_schema import ActionView
from muse.modules.auth.auth_schema import Principal
from muse.modules.conversations.conversations_handler import (
    ConversationNotFound,
    ConversationsHandler,
    MessageRejected,
    WorkflowUnavailable,
)
from muse.modules.conversations.conversations_schema import (
    ConversationStateView,
    ConversationView,
    CreateConversation,
    MessageView,
    SendMessage,
)
from muse.workflows.schema import SendMessageAck

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")


@router.post("", response_model=ConversationView, status_code=status.HTTP_201_CREATED)
async def create(
    body: CreateConversation,
    user: Principal = Depends(current_user),
    handler: ConversationsHandler = Depends(conversations_handler),
) -> ConversationView:
    return await handler.create(user.id, body.title)


@router.get("", response_model=list[ConversationView])
async def list_conversations(
    user: Principal = Depends(current_user),
    handler: ConversationsHandler = Depends(conversations_handler),
) -> list[ConversationView]:
    return await handler.list_for_user(user.id)


@router.get("/{conversation_id}/state", response_model=ConversationStateView)
async def state(
    conversation_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: ConversationsHandler = Depends(conversations_handler),
) -> ConversationStateView:
    try:
        return await handler.state(conversation_id, user.id)
    except ConversationNotFound as exc:
        raise NOT_FOUND from exc


@router.get("/{conversation_id}/messages", response_model=list[MessageView])
async def messages(
    conversation_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: ConversationsHandler = Depends(conversations_handler),
) -> list[MessageView]:
    try:
        return await handler.messages(conversation_id, user.id)
    except ConversationNotFound as exc:
        raise NOT_FOUND from exc


@router.get("/{conversation_id}/actions", response_model=list[ActionView])
async def actions(
    conversation_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: ConversationsHandler = Depends(conversations_handler),
) -> list[ActionView]:
    try:
        return await handler.actions(conversation_id, user.id)
    except ConversationNotFound as exc:
        raise NOT_FOUND from exc


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageAck,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessage,
    user: Principal = Depends(current_user),
    handler: ConversationsHandler = Depends(conversations_handler),
) -> SendMessageAck:
    """Accepted once the message is persisted; the reply arrives via realtime or /state."""
    try:
        return await handler.send_message(user.id, conversation_id, body.content)
    except ConversationNotFound as exc:
        raise NOT_FOUND from exc
    except MessageRejected as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except WorkflowUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "workflow_unavailable") from exc
