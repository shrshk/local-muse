"""Owner login. Passwords are argon2-hashed; sessions are signed, short-lived cookies."""

import datetime as dt
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.ext.asyncio import AsyncEngine

from muse.modules.auth.auth_controller import UsersController
from muse.modules.auth.auth_schema import Principal
from muse.shared.settings import Settings

SESSION_COOKIE = "muse_session"


class InvalidSession(Exception):
    pass


class SessionCodec:
    ALGORITHM = "HS256"
    AUDIENCE = "muse-session"

    def __init__(self, secret: str, ttl_seconds: int) -> None:
        if len(secret) < 32:
            raise ValueError("session secret must be at least 32 characters")
        self._secret = secret
        self._ttl = ttl_seconds

    def encode(self, principal: Principal) -> str:
        now = dt.datetime.now(dt.UTC)
        claims = {
            "sub": str(principal.id),
            "username": principal.username,
            "aud": self.AUDIENCE,
            "iat": int(now.timestamp()),
            "exp": int((now + dt.timedelta(seconds=self._ttl)).timestamp()),
        }
        return jwt.encode(claims, self._secret, algorithm=self.ALGORITHM)

    def decode(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token, self._secret, algorithms=[self.ALGORITHM], audience=self.AUDIENCE
            )
            return Principal(id=uuid.UUID(claims["sub"]), username=claims["username"])
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise InvalidSession from exc


class AuthHandler:
    def __init__(self, engine: AsyncEngine, settings: Settings) -> None:
        self._engine = engine
        self._hasher = PasswordHasher()
        self.sessions = SessionCodec(settings.session_secret, settings.session_ttl_seconds)
        self.session_ttl_seconds = settings.session_ttl_seconds
        # Verified against when the user does not exist, so timing does not reveal usernames.
        self._dummy_hash = self._hasher.hash("not-a-real-password")

    async def authenticate(self, username: str, password: str) -> Principal | None:
        async with self._engine.connect() as conn:
            row = await UsersController(conn).get_by_username(username)
        stored = row["password_hash"] if row else self._dummy_hash
        try:
            self._hasher.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return None
        if row is None:
            return None
        return Principal(id=row["id"], username=row["username"])

    async def create_user(self, username: str, password: str) -> Principal:
        async with self._engine.begin() as conn:
            user_id = await UsersController(conn).insert(username, self._hasher.hash(password))
        return Principal(id=user_id, username=username)
