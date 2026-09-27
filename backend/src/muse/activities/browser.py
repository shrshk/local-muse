"""Browser activities the workflows call: control mode, human input, cleanup.

Human input comes from the owner through the workflow, so it is audited and needs no inbound
port on the worker. It does not go through the policy gateway: the human is the authority.
"""

import uuid
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine
from temporalio import activity
from temporalio.exceptions import ApplicationError

from muse.browser.controller import BrowserActionError, BrowserController, browser_channel
from muse.modules.audit.audit_controller import AuditController
from muse.modules.browser.browser_controller import BrowserSessionsController
from muse.realtime.publisher import RealtimePublisher, conversation_channel
from muse.tools.schema import ExecContext


class BrowserModeInput(BaseModel):
    session_id: uuid.UUID
    mode: Literal["agent", "human"]
    by: str


class BrowserHumanInputInput(BaseModel):
    session_id: uuid.UUID
    action: dict[str, Any]
    by: str


class BrowserCloseInput(BaseModel):
    session_id: uuid.UUID


class BrowserActivities:
    def __init__(
        self, engine: AsyncEngine, controller: BrowserController, publisher: RealtimePublisher
    ) -> None:
        self._engine = engine
        self._controller = controller
        self._publisher = publisher

    @activity.defn(name="browser.set_mode")
    async def set_mode(self, request: BrowserModeInput) -> None:
        async with self._engine.begin() as conn:
            sessions = BrowserSessionsController(conn)
            row = await sessions.get(request.session_id)
            if row is None:
                raise ApplicationError("no such browser session", non_retryable=True)
            await sessions.set(request.session_id, mode=request.mode)
            await AuditController(conn).record(
                "browser.mode",
                _ctx(row, request.by),
                {"session_id": str(request.session_id), "mode": request.mode},
            )
        data = {"session_id": str(request.session_id), "mode": request.mode}
        await self._publisher.publish(browser_channel(request.session_id), "browser.mode", data)
        await self._publisher.publish(
            conversation_channel(row["conversation_id"]), "browser.mode", data
        )

    @activity.defn(name="browser.human_input")
    async def human_input(self, request: BrowserHumanInputInput) -> dict[str, Any]:
        async with self._engine.begin() as conn:
            row = await BrowserSessionsController(conn).get(request.session_id)
            if row is None:
                raise ApplicationError("no such browser session", non_retryable=True)
            await AuditController(conn).record(
                "browser.human_input",
                _ctx(row, request.by),
                {"session_id": str(request.session_id), "kind": request.action.get("kind")},
            )
        try:
            return await self._controller.human_input(request.session_id, request.action)
        except BrowserActionError as exc:
            raise ApplicationError(str(exc), non_retryable=True) from exc

    @activity.defn(name="browser.close")
    async def close(self, request: BrowserCloseInput) -> None:
        if self._controller.get(request.session_id) is not None:
            await self._controller.close(request.session_id)


def _ctx(row: dict[str, Any], by: str) -> ExecContext:
    return ExecContext(
        user_id=row["user_id"],
        conversation_id=row["conversation_id"],
        topic_id=row["topic_id"],
        actor_id=f"human:{by}",
    )
