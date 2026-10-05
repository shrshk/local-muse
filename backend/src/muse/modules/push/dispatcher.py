"""Runs in the backend: turns the notifications outbox into content-free pushes.

Every notification is shown in the app's feed; this decides which ones also interrupt (the
interruption budget) and sends those. Notifications older than REPLAY_WINDOW are never pushed.
"""

import asyncio
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from muse.modules.approvals.approvals_controller import ApprovalsController
from muse.modules.approvals.approvals_schema import ApprovalStatus
from muse.modules.notifications.budget import Importance, should_push
from muse.modules.notifications.notifications_controller import NotificationsController
from muse.modules.push.push_controller import PushController
from muse.modules.push.sender import EndpointNotAllowed, PushError, PushGone, PushSender, Target
from muse.shared.logger import get_logger

logger = get_logger(__name__)

REPLAY_WINDOW_MINUTES = 60
DISPATCH_EVERY_SECONDS = 2.0
APPROVAL_TTL_SECONDS = 24 * 3600
DEFAULT_TTL_SECONDS = 3600


class PushStatus:
    SENT = "sent"
    FAILED = "failed"
    HELD = "held"  # over budget: feed only
    SKIPPED = "skipped"  # no longer relevant (approval already decided)
    NO_DEVICE = "no_device"


class PushDispatcher:
    def __init__(self, engine: AsyncEngine, sender: PushSender) -> None:
        self._engine = engine
        self._sender = sender

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.dispatch_once()
            except SQLAlchemyError as exc:
                logger.warning("push_dispatch_failed", error=type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), DISPATCH_EVERY_SECONDS)
            except TimeoutError:
                pass

    async def dispatch_once(self) -> int:
        sent = 0
        async with self._engine.begin() as conn:
            notifications = NotificationsController(conn)
            for row in await notifications.pending_push(REPLAY_WINDOW_MINUTES):
                status = await self._decide(conn, row)
                if status is None:
                    status = await self._deliver(conn, row)
                await notifications.set_push_status(row["id"], status)
                sent += status == PushStatus.SENT
        return sent

    async def _decide(self, conn: AsyncConnection, row: dict[str, Any]) -> str | None:
        """None means push it; otherwise the final status without pushing."""
        if row["kind"] == "approval" and row["approval_id"] is not None:
            approval = await ApprovalsController(conn).get_row(row["approval_id"])
            if approval is None or approval["status"] != ApprovalStatus.PENDING.value:
                return PushStatus.SKIPPED
            return None
        notifications = NotificationsController(conn)
        pref = await notifications.preference(row["user_id"], row["kind"])
        pushed = await notifications.pushed_today(row["user_id"], row["kind"])
        if should_push(row["kind"], Importance(row["importance"]), pref, pushed):
            return None
        return PushStatus.HELD

    async def _deliver(self, conn: AsyncConnection, row: dict[str, Any]) -> str:
        subscriptions = PushController(conn)
        targets = await subscriptions.for_user(row["user_id"])
        if not targets:
            return PushStatus.NO_DEVICE
        approval = row["kind"] == "approval"
        delivered = False
        for sub in targets:
            try:
                await self._sender.send(
                    Target(sub["endpoint"], sub["p256dh"], sub["auth"]),
                    {"id": str(row["id"])},
                    ttl=APPROVAL_TTL_SECONDS if approval else DEFAULT_TTL_SECONDS,
                    urgency="high" if approval else "normal",
                )
            except (PushGone, EndpointNotAllowed):
                await subscriptions.delete(sub["id"])
                continue
            except PushError as exc:
                logger.warning("push_send_failed", error=str(exc))
                await subscriptions.mark_failure(sub["id"])
                continue
            await subscriptions.mark_success(sub["id"])
            delivered = True
        return PushStatus.SENT if delivered else PushStatus.FAILED
