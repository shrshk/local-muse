import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from muse.api.deps import allowlist_handler, browser_handler, current_user
from muse.modules.auth.auth_schema import Principal
from muse.modules.browser.browser_handler import (
    AllowlistHandler,
    BrowserHandler,
    BrowserInputRejected,
    BrowserSessionNotFound,
    BrowserWorkflowUnavailable,
)
from muse.modules.browser.browser_schema import (
    AllowlistEntry,
    HumanInput,
    PutAllowlistEntry,
    SetModeRequest,
)

router = APIRouter(tags=["browser"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "browser session not found")


@router.get("/api/browser/{session_id}/frame")
async def frame(
    session_id: uuid.UUID,
    user: Principal = Depends(current_user),
    handler: BrowserHandler = Depends(browser_handler),
) -> Response:
    """Latest JPEG frame. Clients append `?v=<frame_version>` from `browser.frame` events."""
    try:
        version, jpeg = await handler.frame(session_id, user.id)
    except BrowserSessionNotFound as exc:
        raise NOT_FOUND from exc
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600", "X-Frame-Version": str(version)},
    )


@router.post("/api/browser/{session_id}/mode", status_code=status.HTTP_204_NO_CONTENT)
async def set_mode(
    session_id: uuid.UUID,
    body: SetModeRequest,
    user: Principal = Depends(current_user),
    handler: BrowserHandler = Depends(browser_handler),
) -> None:
    try:
        await handler.set_mode(session_id, user, body.mode)
    except BrowserSessionNotFound as exc:
        raise NOT_FOUND from exc
    except BrowserInputRejected as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except BrowserWorkflowUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "workflow_unavailable") from exc


@router.post("/api/browser/{session_id}/input")
async def human_input(
    session_id: uuid.UUID,
    body: HumanInput,
    user: Principal = Depends(current_user),
    handler: BrowserHandler = Depends(browser_handler),
) -> dict[str, Any]:
    """Only while you have control (409 otherwise)."""
    try:
        return await handler.human_input(session_id, user, body)
    except BrowserSessionNotFound as exc:
        raise NOT_FOUND from exc
    except BrowserInputRejected as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except BrowserWorkflowUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "workflow_unavailable") from exc


@router.get("/api/allowlist", response_model=list[AllowlistEntry])
async def list_allowlist(
    user: Principal = Depends(current_user),
    handler: AllowlistHandler = Depends(allowlist_handler),
) -> list[AllowlistEntry]:
    return await handler.list_for_user(user.id)


@router.put("/api/allowlist", status_code=status.HTTP_204_NO_CONTENT)
async def add_allowlist(
    body: PutAllowlistEntry,
    user: Principal = Depends(current_user),
    handler: AllowlistHandler = Depends(allowlist_handler),
) -> None:
    await handler.add(user.id, body.domain)


@router.delete("/api/allowlist/{domain}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_allowlist(
    domain: str,
    user: Principal = Depends(current_user),
    handler: AllowlistHandler = Depends(allowlist_handler),
) -> None:
    if not await handler.remove(user.id, domain):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not on the allowlist")
