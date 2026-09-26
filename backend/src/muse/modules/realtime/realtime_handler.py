"""Centrifugo connection tokens: HS256 JWTs with `sub` = user id."""

import datetime as dt

import jwt

from muse.modules.realtime.realtime_schema import ConnectionToken
from muse.shared.settings import Settings


class RealtimeHandler:
    ALGORITHM = "HS256"

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.centrifugo_token_secret
        self._ttl = settings.centrifugo_token_ttl_seconds

    def connection_token(self, user_id: str) -> ConnectionToken:
        now = dt.datetime.now(dt.UTC)
        token = jwt.encode(
            {
                "sub": user_id,
                "iat": int(now.timestamp()),
                "exp": int((now + dt.timedelta(seconds=self._ttl)).timestamp()),
            },
            self._secret,
            algorithm=self.ALGORITHM,
        )
        return ConnectionToken(token=token, expires_in=self._ttl)
