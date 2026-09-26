from fastapi import APIRouter, Depends

from muse.api.deps import health_handler
from muse.modules.health.health_handler import HealthHandler
from muse.modules.health.health_schema import HealthReport

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("", response_model=HealthReport)
async def report(handler: HealthHandler = Depends(health_handler)) -> HealthReport:
    return await handler.report()
