from fastapi import APIRouter, Depends, HTTPException, Response, status

from muse.api.deps import auth_handler, current_user
from muse.modules.auth.auth_handler import SESSION_COOKIE, AuthHandler
from muse.modules.auth.auth_schema import LoginRequest, Principal
from muse.shared.settings import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Principal)
async def login(
    body: LoginRequest, response: Response, auth: AuthHandler = Depends(auth_handler)
) -> Principal:
    principal = await auth.authenticate(body.username, body.password)
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    response.set_cookie(
        SESSION_COOKIE,
        auth.sessions.encode(principal),
        max_age=auth.session_ttl_seconds,
        httponly=True,
        samesite="strict",
        secure=get_settings().session_cookie_secure,
        path="/api",
    )
    return principal


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/api")


@router.get("/me", response_model=Principal)
async def me(user: Principal = Depends(current_user)) -> Principal:
    return user
