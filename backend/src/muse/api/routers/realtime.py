import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from muse.api.deps import conversations_handler, current_user, realtime_handler
from muse.modules.auth.auth_schema import Principal
from muse.modules.conversations.conversations_handler import (
    ConversationNotFound,
    ConversationsHandler,
)
from muse.modules.realtime.realtime_handler import RealtimeHandler
from muse.modules.realtime.realtime_schema import ConnectionToken
from muse.realtime.publisher import conversation_channel

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


class SubscribeRequest(BaseModel):
    conversation_id: uuid.UUID


@router.post("/token", response_model=ConnectionToken)
async def token(
    user: Principal = Depends(current_user),
    handler: RealtimeHandler = Depends(realtime_handler),
) -> ConnectionToken:
    return handler.connection_token(str(user.id))


@router.post("/subscribe_token", response_model=ConnectionToken)
async def subscribe_token(
    body: SubscribeRequest,
    user: Principal = Depends(current_user),
    handler: RealtimeHandler = Depends(realtime_handler),
    conversations: ConversationsHandler = Depends(conversations_handler),
) -> ConnectionToken:
    try:
        await conversations.require_owner(body.conversation_id, user.id)
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found") from exc
    return handler.subscription_token(str(user.id), conversation_channel(body.conversation_id))
