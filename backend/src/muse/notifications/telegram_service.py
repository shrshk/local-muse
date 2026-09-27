"""Runs in the backend: long-polls Telegram for updates and dispatches pending notifications.

Outbound only. The notifications table is the outbox, so delivery survives restarts and never
depends on realtime. Notifications older than REPLAY_WINDOW are not replayed.
"""

import asyncio
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio.service import RPCError

from muse.modules.approvals.approvals_controller import ApprovalsController
from muse.modules.approvals.approvals_schema import ApprovalStatus
from muse.modules.notifications.notifications_controller import NotificationsController
from muse.notifications.telegram_bot import TelegramBot, approval_buttons
from muse.notifications.telegram_client import TelegramClient, TelegramError
from muse.shared.logger import get_logger

logger = get_logger(__name__)

REPLAY_WINDOW_MINUTES = 60
DISPATCH_EVERY_SECONDS = 2.0
BACKOFF_SECONDS = 5.0


class TelegramService:
    def __init__(
        self,
        engine: AsyncEngine,
        client: TelegramClient,
        bot: TelegramBot,
        chat_id: int,
    ) -> None:
        self._engine = engine
        self._client = client
        self._bot = bot
        self._chat_id = chat_id

    async def run(self, stop: asyncio.Event) -> None:
        await asyncio.gather(self._poll(stop), self._dispatch_loop(stop))

    async def _poll(self, stop: asyncio.Event) -> None:
        offset: int | None = None
        while not stop.is_set():
            try:
                updates = await self._client.get_updates(offset)
            except TelegramError as exc:
                logger.warning("telegram_poll_failed", error=str(exc))
                await _wait(stop, BACKOFF_SECONDS)
                continue
            for update in updates:
                offset = int(update["update_id"]) + 1
                try:
                    await self._bot.handle(update)
                except (TelegramError, SQLAlchemyError, RPCError, KeyError, ValueError) as exc:
                    logger.warning("telegram_update_failed", error=type(exc).__name__)

    async def _dispatch_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.dispatch_once()
            except SQLAlchemyError as exc:
                logger.warning("telegram_dispatch_failed", error=type(exc).__name__)
            await _wait(stop, DISPATCH_EVERY_SECONDS)

    async def dispatch_once(self) -> int:
        owner = await self._bot.owner()
        sent = 0
        async with self._engine.begin() as conn:
            notifications = NotificationsController(conn)
            for row in await notifications.pending_telegram(REPLAY_WINDOW_MINUTES):
                if owner is None or row["user_id"] != owner.id:
                    await notifications.set_telegram(row["id"], telegram_status="skipped")
                    continue
                text, buttons = await self._render(conn, row)
                if text is None:
                    await notifications.set_telegram(row["id"], telegram_status="skipped")
                    continue
                try:
                    message_id = await self._client.send_message(self._chat_id, text, buttons)
                except TelegramError as exc:
                    logger.warning("telegram_send_failed", error=str(exc))
                    await notifications.set_telegram(row["id"], telegram_status="failed")
                    continue
                await notifications.set_telegram(
                    row["id"],
                    telegram_status="sent",
                    telegram_chat_id=self._chat_id,
                    telegram_message_id=message_id,
                )
                sent += 1
        return sent

    async def _render(
        self, conn: Any, row: dict[str, Any]
    ) -> tuple[str | None, list[list[dict[str, str]]] | None]:
        if row["kind"] != "approval" or row["approval_id"] is None:
            return f"{row['title']}\n{row['body']}", None
        approval = await ApprovalsController(conn).get_row(row["approval_id"])
        if approval is None or approval["status"] != ApprovalStatus.PENDING.value:
            return None, None  # decided before we got to it
        expires = approval["expires_at"].strftime("%Y-%m-%d %H:%M UTC")
        text = f"Approval needed\n{approval['summary']}\n(expires {expires})"
        return text, approval_buttons(approval["id"], approval["approval_key"])


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), seconds)
    except TimeoutError:
        pass
