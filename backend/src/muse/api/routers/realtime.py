from fastapi import APIRouter, Depends

from muse.api.deps import current_user, realtime_handler
from muse.modules.auth.auth_schema import Principal
from muse.modules.realtime.realtime_handler import RealtimeHandler
from muse.modules.realtime.realtime_schema import ConnectionToken

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


@router.post("/token", response_model=ConnectionToken)
async def token(
    user: Principal = Depends(current_user),
    handler: RealtimeHandler = Depends(realtime_handler),
) -> ConnectionToken:
    return handler.connection_token(str(user.id))
