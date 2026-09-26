from fastapi import APIRouter, Depends

from muse.api.deps import model_provider
from muse.models.provider import ModelProvider, ProviderHealth

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/health", response_model=ProviderHealth)
async def health(provider: ModelProvider = Depends(model_provider)) -> ProviderHealth:
    return await provider.health()
