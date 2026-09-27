"""browser.*: the entire browser surface the model gets. No evaluate, no CDP, no raw Playwright.

One session per topic (or per conversation for the coordinator). Research context only until
Phase 8. While a human has control, every call is deferred and the workflow waits.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from muse.browser.controller import BrowserActionError, BrowserController, Session, SessionOwner
from muse.tools.errors import ToolDeferred, ToolExecutionError
from muse.tools.schema import ExecContext, ToolServices

ELEMENT_ID = Field(pattern=r"^e\d{1,4}$", description="Element id from the latest snapshot")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenArgs(Strict):
    context: Literal["research", "authenticated"] = "research"


class NavigateArgs(Strict):
    url: str = Field(max_length=2000, description="http(s) URL")


class NoArgs(Strict):
    pass


class ElementArgs(Strict):
    element_id: str = ELEMENT_ID


class FillArgs(Strict):
    element_id: str = ELEMENT_ID
    text: str = Field(max_length=2000)


class PressArgs(Strict):
    element_id: str = ELEMENT_ID
    key: str = Field(max_length=30, description="e.g. Enter, Tab, ArrowDown")


class ScrollArgs(Strict):
    direction: Literal["up", "down"] = "down"


def session_key(ctx: ExecContext) -> uuid.UUID:
    return ctx.topic_id or ctx.conversation_id


def _owner(ctx: ExecContext) -> SessionOwner:
    return SessionOwner(
        user_id=ctx.user_id,
        conversation_id=ctx.conversation_id,
        topic_id=ctx.topic_id,
        workflow_id=ctx.workflow_id or "",
    )


async def _browser(ctx: ExecContext, services: ToolServices) -> BrowserController:
    if services.browser is None:
        raise ToolExecutionError("no browser available here")
    if await services.browser.mode(session_key(ctx)) == "human":
        raise ToolDeferred({"reason": "human_takeover", "session_id": str(session_key(ctx))})
    return services.browser


async def _page(ctx: ExecContext, services: ToolServices) -> tuple[BrowserController, Session]:
    browser = await _browser(ctx, services)
    session = browser.get(session_key(ctx))
    if session is None:
        raise ToolExecutionError("no page is open (the browser may have restarted); navigate first")
    return browser, session


async def open_session(args: OpenArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    browser = await _browser(ctx, services)
    try:
        session = await browser.open(session_key(ctx), _owner(ctx), args.context)
    except BrowserActionError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return {"session": str(session.id), "context": session.context_kind}


async def navigate(args: NavigateArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    browser = await _browser(ctx, services)
    try:
        session = browser.get(session_key(ctx)) or await browser.open(session_key(ctx), _owner(ctx))
        return await browser.navigate(session, args.url)
    except BrowserActionError as exc:
        raise ToolExecutionError(str(exc)) from exc


async def snapshot(args: NoArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    browser, session = await _page(ctx, services)
    try:
        return await browser.snapshot(session)
    except BrowserActionError as exc:
        raise ToolExecutionError(str(exc)) from exc


async def screenshot(args: NoArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    browser, session = await _page(ctx, services)
    return await browser.screenshot(session, _owner(ctx))


async def click(args: ElementArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    browser, session = await _page(ctx, services)
    try:
        return await browser.click(session, args.element_id)
    except BrowserActionError as exc:
        raise ToolExecutionError(str(exc)) from exc


async def fill(args: FillArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    browser, session = await _page(ctx, services)
    try:
        return await browser.fill(session, args.element_id, args.text)
    except BrowserActionError as exc:
        raise ToolExecutionError(str(exc)) from exc


async def press(args: PressArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    browser, session = await _page(ctx, services)
    try:
        return await browser.press(session, args.element_id, args.key)
    except BrowserActionError as exc:
        raise ToolExecutionError(str(exc)) from exc


async def scroll(args: ScrollArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    browser, session = await _page(ctx, services)
    return await browser.scroll(session, args.direction)


async def download(args: ElementArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    browser, session = await _page(ctx, services)
    try:
        return await browser.download(session, args.element_id, _owner(ctx))
    except BrowserActionError as exc:
        raise ToolExecutionError(str(exc)) from exc


async def close_session(args: NoArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    if services.browser is None:
        raise ToolExecutionError("no browser available here")
    await services.browser.close(session_key(ctx))
    return {"closed": True}
