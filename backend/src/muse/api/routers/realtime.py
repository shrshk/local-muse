from fastapi import APIRouter, Depends

from muse.api.deps import current_user_id, realtime_handler
from muse.modules.realtime.realtime_handler import RealtimeHandler
from muse.modules.realtime.realtime_schema import ConnectionToken

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


@router.post("/token", response_model=ConnectionToken)
async def token(
    user_id: str = Depends(current_user_id),
    handler: RealtimeHandler = Depends(realtime_handler),
) -> ConnectionToken:
    return handler.connection_token(user_id)
