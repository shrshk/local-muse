import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from muse.api.deps import current_user, topics_handler
from muse.modules.auth.auth_schema import Principal
from muse.modules.topics.topics_handler import (
    StaleMemoryVersion,
    TopicNotActive,
    TopicNotFound,
    TopicsHandler,
)
from muse.modules.topics.topics_schema import TopicMemoryView, TopicView, UpdateTopicMemory

router = APIRouter(prefix="/api/topics", tags=["topics"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "topic not found")


@router.get("/{topic_id}", response_model=TopicView)
async def get_topic(
    topic_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: TopicsHandler = Depends(topics_handler),
) -> TopicView:
    try:
        return await handler.get(topic_id, user.id)
    except TopicNotFound as exc:
        raise NOT_FOUND from exc


@router.post("/{topic_id}/cancel", response_model=TopicView, status_code=status.HTTP_202_ACCEPTED)
async def cancel(
    topic_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: TopicsHandler = Depends(topics_handler),
) -> TopicView:
    """Accepted; the topic records `cancelled` once its cleanup has run."""
    try:
        return await handler.cancel(topic_id, user.id)
    except TopicNotFound as exc:
        raise NOT_FOUND from exc
    except TopicNotActive as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"topic is {exc}") from exc


@router.get("/{topic_id}/memory", response_model=TopicMemoryView)
async def memory(
    topic_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: TopicsHandler = Depends(topics_handler),
) -> TopicMemoryView:
    try:
        return await handler.memory(topic_id, user.id)
    except TopicNotFound as exc:
        raise NOT_FOUND from exc


@router.put("/{topic_id}/memory", response_model=TopicMemoryView)
async def update_memory(
    topic_id: uuid.UUID,
    body: UpdateTopicMemory,
    user: Principal = Depends(current_user),
    handler: TopicsHandler = Depends(topics_handler),
) -> TopicMemoryView:
    try:
        return await handler.update_memory(topic_id, user.id, body)
    except TopicNotFound as exc:
        raise NOT_FOUND from exc
    except StaleMemoryVersion as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "memory changed; reload and retry") from exc
