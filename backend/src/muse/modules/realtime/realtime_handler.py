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
        return ConnectionToken(token=self._sign({"sub": user_id}), expires_in=self._ttl)

    def subscription_token(self, user_id: str, channel: str) -> ConnectionToken:
        """Callers must check the user owns the channel's resource first."""
        return ConnectionToken(
            token=self._sign({"sub": user_id, "channel": channel}), expires_in=self._ttl
        )

    def _sign(self, claims: dict[str, str]) -> str:
        now = dt.datetime.now(dt.UTC)
        return jwt.encode(
            {
                **claims,
                "iat": int(now.timestamp()),
                "exp": int((now + dt.timedelta(seconds=self._ttl)).timestamp()),
            },
            self._secret,
            algorithm=self.ALGORITHM,
        )
