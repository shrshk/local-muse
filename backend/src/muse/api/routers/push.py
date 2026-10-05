from fastapi import APIRouter, Depends, Header, HTTPException, status

from muse.api.deps import current_user, push_handler
from muse.modules.auth.auth_schema import Principal
from muse.modules.push.push_handler import PushHandler, SubscriptionRejected
from muse.modules.push.push_schema import PublicKey, Subscribe, SubscriptionView, Unsubscribe

router = APIRouter(tags=["push"])


@router.get("/api/push/key", response_model=PublicKey)
async def public_key(
    user: Principal = Depends(current_user),
    handler: PushHandler = Depends(push_handler),
) -> PublicKey:
    return handler.public_key()


@router.post("/api/push/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    body: Subscribe,
    user_agent: str | None = Header(default=None),
    user: Principal = Depends(current_user),
    handler: PushHandler = Depends(push_handler),
) -> None:
    try:
        await handler.subscribe(user.id, body, user_agent)
    except SubscriptionRejected as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/api/push/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    body: Unsubscribe,
    user: Principal = Depends(current_user),
    handler: PushHandler = Depends(push_handler),
) -> None:
    await handler.unsubscribe(user.id, body.endpoint)


@router.get("/api/push/subscriptions", response_model=list[SubscriptionView])
async def devices(
    user: Principal = Depends(current_user),
    handler: PushHandler = Depends(push_handler),
) -> list[SubscriptionView]:
    return await handler.devices(user.id)


@router.post("/api/push/test", status_code=status.HTTP_202_ACCEPTED)
async def test_push(
    user: Principal = Depends(current_user),
    handler: PushHandler = Depends(push_handler),
) -> None:
    await handler.test(user.id)
