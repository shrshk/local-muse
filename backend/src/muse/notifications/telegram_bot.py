"""Handles Telegram updates: approval buttons and a few commands, for allowed chats only.

Telegram owns no state. A callback is honoured only if the chat is allowed, the approval belongs
to the owner, its key matches the one on the button, and it is still pending; then it goes
through the same decision path as the web (a Temporal Update). Duplicates are no-ops.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from muse.modules.approvals.approvals_controller import ApprovalsController
from muse.modules.approvals.approvals_handler import (
    ApprovalExpired,
    ApprovalNotFound,
    ApprovalsHandler,
    ApprovalWorkflowUnavailable,
)
from muse.modules.approvals.approvals_schema import ApprovalStatus, DecisionRequest
from muse.modules.audit.audit_controller import AuditController
from muse.modules.auth.auth_controller import UsersController
from muse.modules.auth.auth_schema import Principal
from muse.modules.goals.goals_controller import GoalsController
from muse.modules.goals.goals_schema import GoalStatus
from muse.modules.topics.topics_controller import TopicsController
from muse.modules.topics.topics_handler import TopicNotActive, TopicNotFound, TopicsHandler
from muse.notifications.telegram_client import TelegramClient
from muse.shared.logger import get_logger

logger = get_logger(__name__)

KEY_PREFIX = 16
HELP = (
    "Local Muse. Commands:\n"
    "/status — pending approvals, topics and goals\n"
    "/topics — running topics\n"
    "/cancel <topic id prefix> — cancel a topic\n"
    "Approvals arrive here with Approve / Deny buttons."
)


def approval_buttons(approval_id: uuid.UUID, approval_key: str) -> list[list[dict[str, str]]]:
    base = f"a:{approval_id}:{approval_key[:KEY_PREFIX]}"
    return [
        [
            {"text": "Approve", "callback_data": f"{base}:y"},
            {"text": "Deny", "callback_data": f"{base}:n"},
        ]
    ]


def parse_callback(data: str) -> tuple[uuid.UUID, str, bool] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "a" or parts[3] not in ("y", "n"):
        return None
    try:
        approval_id = uuid.UUID(parts[1])
    except ValueError:
        return None
    return approval_id, parts[2], parts[3] == "y"


class TelegramBot:
    def __init__(
        self,
        engine: AsyncEngine,
        client: TelegramClient,
        allowed_chats: frozenset[int],
        owner_username: str,
        approvals: ApprovalsHandler,
        topics: TopicsHandler,
    ) -> None:
        self._engine = engine
        self._client = client
        self._allowed = allowed_chats
        self._owner_username = owner_username
        self._approvals = approvals
        self._topics = topics
        self._owner: Principal | None = None

    async def owner(self) -> Principal | None:
        if self._owner is None:
            async with self._engine.connect() as conn:
                row = await UsersController(conn).get_by_username(self._owner_username)
            if row is not None:
                self._owner = Principal(id=row["id"], username=row["username"])
        return self._owner

    async def handle(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            await self._callback(update["callback_query"])
        elif "message" in update:
            await self._message(update["message"])

    async def _audit(self, event_type: str, chat_id: int, payload: dict[str, Any]) -> None:
        async with self._engine.begin() as conn:
            await AuditController(conn).record_raw(event_type, f"telegram:{chat_id}", payload)

    async def _gate(self, chat_id: int, kind: str) -> Principal | None:
        owner = await self.owner()
        if chat_id not in self._allowed or owner is None:
            await self._audit("telegram.ignored", chat_id, {"kind": kind})
            logger.warning("telegram_chat_ignored", chat_id=chat_id, kind=kind)
            return None
        await self._audit("telegram.inbound", chat_id, {"kind": kind})
        return owner

    async def _message(self, message: dict[str, Any]) -> None:
        chat_id = int(message.get("chat", {}).get("id", 0))
        owner = await self._gate(chat_id, "message")
        if owner is None:
            return
        command, _, argument = str(message.get("text", "")).strip().partition(" ")
        if command == "/status":
            reply = await self._status(owner)
        elif command == "/topics":
            reply = await self._list_topics(owner)
        elif command == "/cancel":
            reply = await self._cancel(owner, argument.strip())
        else:
            reply = HELP
        await self._client.send_message(chat_id, reply)

    async def _callback(self, callback: dict[str, Any]) -> None:
        chat_id = int(callback.get("message", {}).get("chat", {}).get("id", 0))
        owner = await self._gate(chat_id, "callback")
        if owner is None:
            return
        parsed = parse_callback(str(callback.get("data", "")))
        if parsed is None:
            await self._client.answer_callback(callback["id"], "Unknown button.")
            return
        approval_id, key_prefix, approve = parsed
        text = await self._decide(owner, approval_id, key_prefix, approve)
        await self._client.answer_callback(callback["id"], text)
        message = callback.get("message", {})
        if "message_id" in message:
            original = str(message.get("text", "Approval"))
            await self._client.edit_text(
                chat_id, int(message["message_id"]), f"{original}\n\n→ {text}"
            )

    async def _decide(
        self, owner: Principal, approval_id: uuid.UUID, key_prefix: str, approve: bool
    ) -> str:
        async with self._engine.connect() as conn:
            approval = await ApprovalsController(conn).get_owned(approval_id, owner.id)
        if approval is None:
            return "Not found."
        if not approval.approval_key.startswith(key_prefix):
            return "This button does not match the action."
        request = DecisionRequest(
            decision="approve" if approve else "deny", approval_key=approval.approval_key
        )
        try:
            result = await self._approvals.decide(approval_id, owner, request, channel="telegram")
        except ApprovalNotFound:
            return "Not found."
        except ApprovalExpired:
            return "Expired."
        except ApprovalWorkflowUnavailable:
            return "Could not reach the workflow; try again."
        if not result.changed:
            return f"Already decided: {result.approval.status.value.lower()}."
        return "Approved." if result.approval.status is ApprovalStatus.APPROVED else "Denied."

    async def _status(self, owner: Principal) -> str:
        async with self._engine.connect() as conn:
            pending = await ApprovalsController(conn).list_for_user(
                owner.id, ApprovalStatus.PENDING
            )
            goals = [
                g
                for g in await GoalsController(conn).list_for_user(owner.id)
                if g.status is GoalStatus.ACTIVE
            ]
            running = await self._running_topics(conn, owner.id)
        return (
            f"Pending approvals: {len(pending)}\n"
            f"Running topics: {len(running)}\n"
            f"Active goals: {len(goals)}"
        )

    async def _list_topics(self, owner: Principal) -> str:
        async with self._engine.connect() as conn:
            running = await self._running_topics(conn, owner.id)
        if not running:
            return "No running topics."
        return "\n".join(f"{str(t_id)[:8]}  {title}" for t_id, title in running)

    async def _cancel(self, owner: Principal, prefix: str) -> str:
        if len(prefix) < 4:
            return "Usage: /cancel <first characters of the topic id>"
        async with self._engine.connect() as conn:
            running = await self._running_topics(conn, owner.id)
        matches = [t_id for t_id, _ in running if str(t_id).startswith(prefix)]
        if len(matches) != 1:
            return "No single running topic matches that prefix."
        try:
            topic = await self._topics.cancel(matches[0], owner.id)
        except (TopicNotFound, TopicNotActive):
            return "That topic is not running."
        return f"Cancelling “{topic.title}”."

    async def _running_topics(
        self, conn: AsyncConnection, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, str]]:
        return [(t.id, t.title) for t in await TopicsController(conn).running_for_user(user_id)]
