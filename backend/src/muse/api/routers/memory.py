from fastapi import APIRouter, Depends, HTTPException, status

from muse.api.deps import current_user, profile_memory_handler
from muse.modules.auth.auth_schema import Principal
from muse.modules.memory.memory_handler import FactNotFound, InvalidFact, ProfileMemoryHandler
from muse.modules.memory.memory_schema import ProfileFact, PutProfileFact

router = APIRouter(prefix="/api/profile/memory", tags=["memory"])


@router.get("", response_model=list[ProfileFact])
async def list_facts(
    user: Principal = Depends(current_user),
    handler: ProfileMemoryHandler = Depends(profile_memory_handler),
) -> list[ProfileFact]:
    return await handler.list_for_user(user.id)


@router.put("/{key}", response_model=ProfileFact)
async def put_fact(
    key: str,
    body: PutProfileFact,
    user: Principal = Depends(current_user),
    handler: ProfileMemoryHandler = Depends(profile_memory_handler),
) -> ProfileFact:
    try:
        return await handler.put(user.id, key, body.value)
    except InvalidFact as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(
    key: str,
    user: Principal = Depends(current_user),
    handler: ProfileMemoryHandler = Depends(profile_memory_handler),
) -> None:
    try:
        await handler.delete(user.id, key)
    except FactNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such fact") from exc
