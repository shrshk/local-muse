import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from muse.api.deps import conversations_handler, current_user
from muse.modules.actions.actions_schema import ActionView
from muse.modules.auth.auth_schema import Principal
from muse.modules.conversations.conversations_handler import (
    ConversationNotFound,
    ConversationsHandler,
    ModelUnavailable,
)
from muse.modules.conversations.conversations_schema import (
    ConversationView,
    CreateConversation,
    MessageView,
    SendMessage,
    TurnResult,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


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


@router.get("/{conversation_id}/messages", response_model=list[MessageView])
async def messages(
    conversation_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: ConversationsHandler = Depends(conversations_handler),
) -> list[MessageView]:
    try:
        return await handler.messages(conversation_id, user.id)
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found") from exc


@router.get("/{conversation_id}/actions", response_model=list[ActionView])
async def actions(
    conversation_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: ConversationsHandler = Depends(conversations_handler),
) -> list[ActionView]:
    try:
        return await handler.actions(conversation_id, user.id)
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found") from exc


@router.post("/{conversation_id}/messages", response_model=TurnResult)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessage,
    user: Principal = Depends(current_user),
    handler: ConversationsHandler = Depends(conversations_handler),
) -> TurnResult:
    try:
        return await handler.send_message(user.id, conversation_id, body.content)
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found") from exc
    except ModelUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "model_unavailable") from exc
