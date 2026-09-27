"""Browser viewer, human takeover and the research-domain allowlist, for the owner."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio.client import WorkflowUpdateFailedError
from temporalio.service import RPCError

from muse.activities.browser import BrowserHumanInputInput, BrowserModeInput
from muse.modules.auth.auth_schema import Principal
from muse.modules.browser.browser_controller import (
    AllowlistController,
    BrowserSessionsController,
    InputInboxController,
)
from muse.modules.browser.browser_schema import (
    AllowlistEntry,
    BrowserMode,
    BrowserSessionView,
    HumanInput,
)
from muse.shared.logger import get_logger
from muse.shared.temporal import TemporalClientProvider

logger = get_logger(__name__)

RESEARCH = "research"


class BrowserSessionNotFound(Exception):
    pass


class BrowserInputRejected(Exception):
    pass


class BrowserWorkflowUnavailable(Exception):
    pass


class BrowserHandler:
    def __init__(self, engine: AsyncEngine, temporal: TemporalClientProvider) -> None:
        self._engine = engine
        self._temporal = temporal

    async def sessions(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[BrowserSessionView]:
        async with self._engine.connect() as conn:
            return await BrowserSessionsController(conn).list_for_conversation(
                conversation_id, user_id
            )

    async def require_owner(self, session_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
        async with self._engine.connect() as conn:
            row = await BrowserSessionsController(conn).get_owned(session_id, user_id)
        if row is None:
            raise BrowserSessionNotFound(str(session_id))
        return row

    async def frame(self, session_id: uuid.UUID, user_id: uuid.UUID) -> tuple[int, bytes]:
        await self.require_owner(session_id, user_id)
        async with self._engine.connect() as conn:
            frame = await BrowserSessionsController(conn).frame(session_id)
        if frame is None:
            raise BrowserSessionNotFound(str(session_id))
        return frame

    async def set_mode(self, session_id: uuid.UUID, user: Principal, mode: BrowserMode) -> None:
        row = await self.require_owner(session_id, user.id)
        await self._update(
            row["workflow_id"],
            "set_browser_mode",
            BrowserModeInput(session_id=session_id, mode=mode, by=user.username),
            None,
        )

    async def human_input(
        self, session_id: uuid.UUID, user: Principal, action: HumanInput
    ) -> dict[str, Any]:
        row = await self.require_owner(session_id, user.id)
        payload = action.model_dump(exclude_none=True)
        if action.kind == "type" and action.text:
            # Typed text may be a password: park it in the inbox, send only its id.
            async with self._engine.begin() as conn:
                inbox_id = await InputInboxController(conn).put(session_id, action.text)
            payload = {"kind": "type", "inbox_id": str(inbox_id)}
        result: dict[str, Any] = await self._update(
            row["workflow_id"],
            "browser_human_input",
            BrowserHumanInputInput(session_id=session_id, action=payload, by=user.username),
            dict,
        )
        return result

    async def _update(self, workflow_id: str, name: str, arg: Any, result_type: Any) -> Any:
        try:
            client = await self._temporal.get()
            return await client.get_workflow_handle(workflow_id).execute_update(
                name, arg, result_type=result_type
            )
        except WorkflowUpdateFailedError as exc:
            raise BrowserInputRejected(str(exc.cause)) from exc
        except RPCError as exc:
            logger.warning("browser_update_failed", workflow_id=workflow_id, error=exc.status.name)
            raise BrowserWorkflowUnavailable(workflow_id) from exc


class AllowlistHandler:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list_for_user(self, user_id: uuid.UUID) -> list[AllowlistEntry]:
        async with self._engine.connect() as conn:
            return await AllowlistController(conn).list_for_user(user_id)

    async def add(self, user_id: uuid.UUID, domain: str) -> None:
        async with self._engine.begin() as conn:
            await AllowlistController(conn).add(user_id, domain.lower(), RESEARCH)

    async def remove(self, user_id: uuid.UUID, domain: str) -> bool:
        async with self._engine.begin() as conn:
            return await AllowlistController(conn).remove(user_id, domain.lower(), RESEARCH)
