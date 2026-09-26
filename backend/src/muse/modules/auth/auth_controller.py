"""Queries for users."""

import uuid

from sqlalchemy import insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.shared.tables import users


class UsersController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get_by_username(self, username: str) -> RowMapping | None:
        stmt = select(users).where(users.c.username == username)
        return (await self._conn.execute(stmt)).mappings().first()

    async def insert(self, username: str, password_hash: str) -> uuid.UUID:
        stmt = (
            insert(users)
            .values(username=username, password_hash=password_hash)
            .returning(users.c.id)
        )
        user_id: uuid.UUID = (await self._conn.execute(stmt)).scalar_one()
        return user_id
