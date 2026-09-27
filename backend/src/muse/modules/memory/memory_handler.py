"""User reads and edits of profile memory."""

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from muse.memory.secrets import looks_like_secret
from muse.modules.memory.memory_controller import ProfileMemoryController
from muse.modules.memory.memory_schema import KEY_PATTERN, ProfileFact


class InvalidFact(Exception):
    pass


class FactNotFound(Exception):
    pass


def validate_fact(key: str, value: str) -> None:
    if not re.fullmatch(KEY_PATTERN, key):
        raise InvalidFact("key must be lowercase letters, digits, '_', '.', '-' (max 64)")
    if looks_like_secret(value) or looks_like_secret(key):
        raise InvalidFact("that looks like a secret; memory never stores secrets")


class ProfileMemoryHandler:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list_for_user(self, user_id: uuid.UUID) -> list[ProfileFact]:
        async with self._engine.connect() as conn:
            return await ProfileMemoryController(conn).list_for_user(user_id)

    async def put(self, user_id: uuid.UUID, key: str, value: str) -> ProfileFact:
        validate_fact(key, value)
        async with self._engine.begin() as conn:
            return await ProfileMemoryController(conn).put(user_id, key, value, "user")

    async def delete(self, user_id: uuid.UUID, key: str) -> None:
        async with self._engine.begin() as conn:
            if not await ProfileMemoryController(conn).delete(user_id, key):
                raise FactNotFound(key)
