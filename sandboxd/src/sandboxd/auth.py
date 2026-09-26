"""Bearer-token check. Defence in depth behind the internal sandbox-control network."""

import hmac

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def require_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    expected: str = request.app.state.settings.sandboxd_token
    if credentials is None or not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
