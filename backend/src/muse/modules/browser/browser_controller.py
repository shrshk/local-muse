"""Queries for browser sessions, frames and the domain allowlist."""

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.modules.browser.browser_schema import AllowlistEntry, BrowserSessionView
from muse.shared.tables import browser_frames, browser_sessions, domain_allowlist


class BrowserSessionsController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def upsert(self, session_id: uuid.UUID, **values: Any) -> None:
        stmt = insert(browser_sessions).values(id=session_id, status="open", **values)
        await self._conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[browser_sessions.c.id],
                set_={"status": "open", "context": values["context"], "updated_at": func.now()},
            )
        )

    async def get(self, session_id: uuid.UUID) -> dict[str, Any] | None:
        stmt = select(browser_sessions).where(browser_sessions.c.id == session_id)
        row = (await self._conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def get_owned(self, session_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any] | None:
        row = await self.get(session_id)
        return row if row and row["user_id"] == user_id else None

    async def list_for_conversation(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[BrowserSessionView]:
        stmt = (
            select(browser_sessions)
            .where(
                browser_sessions.c.conversation_id == conversation_id,
                browser_sessions.c.user_id == user_id,
            )
            .order_by(browser_sessions.c.created_at)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [BrowserSessionView.model_validate(dict(r)) for r in rows]

    async def set(self, session_id: uuid.UUID, **values: Any) -> None:
        await self._conn.execute(
            update(browser_sessions)
            .where(browser_sessions.c.id == session_id)
            .values(updated_at=func.now(), **values)
        )

    async def save_frame(self, session_id: uuid.UUID, jpeg: bytes, url: str) -> int:
        version: int = (
            await self._conn.execute(
                update(browser_sessions)
                .where(browser_sessions.c.id == session_id)
                .values(
                    frame_version=browser_sessions.c.frame_version + 1,
                    current_url=url,
                    updated_at=func.now(),
                )
                .returning(browser_sessions.c.frame_version)
            )
        ).scalar_one()
        upsert = insert(browser_frames).values(session_id=session_id, version=version, jpeg=jpeg)
        await self._conn.execute(
            upsert.on_conflict_do_update(
                index_elements=[browser_frames.c.session_id],
                set_={"version": version, "jpeg": jpeg, "updated_at": func.now()},
            )
        )
        return version

    async def frame(self, session_id: uuid.UUID) -> tuple[int, bytes] | None:
        stmt = select(browser_frames.c.version, browser_frames.c.jpeg).where(
            browser_frames.c.session_id == session_id
        )
        row = (await self._conn.execute(stmt)).first()
        return (row.version, bytes(row.jpeg)) if row else None


class AllowlistController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list_for_user(self, user_id: uuid.UUID) -> list[AllowlistEntry]:
        stmt = (
            select(domain_allowlist)
            .where(domain_allowlist.c.user_id == user_id)
            .order_by(domain_allowlist.c.domain)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return [AllowlistEntry.model_validate(dict(r)) for r in rows]

    async def add(self, user_id: uuid.UUID, domain: str, context: str) -> None:
        stmt = insert(domain_allowlist).values(user_id=user_id, domain=domain, context=context)
        await self._conn.execute(stmt.on_conflict_do_nothing())

    async def remove(self, user_id: uuid.UUID, domain: str, context: str) -> bool:
        stmt = delete(domain_allowlist).where(
            domain_allowlist.c.user_id == user_id,
            domain_allowlist.c.domain == domain,
            domain_allowlist.c.context == context,
        )
        return bool((await self._conn.execute(stmt)).rowcount)
