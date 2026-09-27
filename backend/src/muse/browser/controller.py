"""Owns Playwright in the worker process.

Research sessions get their own fresh Chromium context (no cookies, no saved state).
Authenticated sessions get a page in the user's persistent profile context, whose directory is
on a worker-only volume and is a credential. Sessions are keyed by topic (or conversation for the
coordinator) and are not durable. Every request of every context passes the HostGuard.
"""

import asyncio
import pathlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Route,
    ViewportSize,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from sqlalchemy.ext.asyncio import AsyncEngine

from muse.browser.netguard import BlockedURL, HostGuard, domain_of, validate_url
from muse.browser.snapshot import element_selector, take_snapshot
from muse.modules.artifacts.store import ArtifactStore
from muse.modules.browser.browser_controller import BrowserSessionsController
from muse.policy.classification import BrowserContext as ContextKind
from muse.policy.classification import DataClassification
from muse.realtime.publisher import RealtimePublisher
from muse.shared.logger import get_logger

logger = get_logger(__name__)

VIEWPORT: ViewportSize = {"width": 1280, "height": 800}
ACTION_TIMEOUT_MS = 15_000
NAVIGATION_TIMEOUT_MS = 30_000
FRAME_QUALITY = 55
ELEMENT_ID = re.compile(r"^e\d{1,4}$")
KEY_NAME = re.compile(r"^[A-Za-z0-9+]{1,30}$")


class BrowserActionError(Exception):
    """Expected failure; the message is safe to show the model."""


def browser_channel(session_id: uuid.UUID) -> str:
    return f"browser:{session_id}"


@dataclass(frozen=True)
class BrowserFacts:
    context: ContextKind = "research"
    domain: str | None = None
    element_name: str | None = None


@dataclass
class Session:
    id: uuid.UUID
    user_id: uuid.UUID
    context_kind: ContextKind
    context: BrowserContext
    page: Page
    owns_context: bool = True
    elements: dict[str, str] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True)
class SessionOwner:
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    topic_id: uuid.UUID | None
    workflow_id: str


class BrowserController:
    def __init__(
        self,
        engine: AsyncEngine,
        artifacts: ArtifactStore,
        publisher: RealtimePublisher | None,
        profile_root: pathlib.Path | None = None,
    ) -> None:
        self._engine = engine
        self._profile_root = profile_root
        self._auth_contexts: dict[uuid.UUID, BrowserContext] = {}
        self._artifacts = artifacts
        self._publisher = publisher
        self._guard = HostGuard()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._sessions: dict[uuid.UUID, Session] = {}
        self._start_lock = asyncio.Lock()

    # -- lifecycle ------------------------------------------------------------------------

    async def _browser_instance(self) -> Browser:
        async with self._start_lock:
            if self._browser is None or not self._browser.is_connected():
                self._playwright = self._playwright or await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    args=["--disable-dev-shm-usage"]
                )
        return self._browser

    async def _auth_context(self, user_id: uuid.UUID) -> BrowserContext:
        """The user's persistent profile. Chromium locks the directory, so one context per user."""
        if self._profile_root is None:
            raise BrowserActionError("no browser profile is configured")
        async with self._start_lock:
            context = self._auth_contexts.get(user_id)
            if context is not None:
                return context
            self._playwright = self._playwright or await async_playwright().start()
            directory = self._profile_root / str(user_id)
            await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
            context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(directory),
                viewport=VIEWPORT,
                accept_downloads=True,
                args=["--disable-dev-shm-usage"],
            )
            await context.route("**/*", self._guard_route)
            self._auth_contexts[user_id] = context
            return context

    async def stop(self) -> None:
        for session_id in list(self._sessions):
            await self.close(session_id)
        for context in list(self._auth_contexts.values()):
            await context.close()
        self._auth_contexts.clear()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def open(
        self, session_id: uuid.UUID, owner: SessionOwner, kind: ContextKind = "research"
    ) -> Session:
        existing = self._sessions.get(session_id)
        if existing and existing.context_kind == kind and not existing.page.is_closed():
            return existing
        if existing:
            await self.close(session_id)
        if kind == "authenticated":
            context = await self._auth_context(owner.user_id)
            blank = [p for p in context.pages if p.url == "about:blank" and not self._in_use(p)]
            page = blank[0] if blank else await context.new_page()
            owns_context = False
        else:
            browser = await self._browser_instance()
            context = await browser.new_context(viewport=VIEWPORT, accept_downloads=True)
            await context.route("**/*", self._guard_route)
            page = await context.new_page()
            owns_context = True
        session = Session(
            id=session_id,
            user_id=owner.user_id,
            context_kind=kind,
            context=context,
            page=page,
            owns_context=owns_context,
        )
        self._watch(session, page)
        self._sessions[session_id] = session
        async with self._engine.begin() as conn:
            await BrowserSessionsController(conn).upsert(
                session_id,
                user_id=owner.user_id,
                conversation_id=owner.conversation_id,
                topic_id=owner.topic_id,
                workflow_id=owner.workflow_id,
                context=kind,
            )
        return session

    def _watch(self, session: Session, page: Page) -> None:
        page.on("popup", lambda popup: self._adopt(session, popup))
        page.on("framenavigated", lambda frame: self._on_navigated(session, frame.parent_frame))

    def _in_use(self, page: Page) -> bool:
        return any(s.page is page for s in self._sessions.values())

    async def close(self, session_id: uuid.UUID) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            try:
                if session.owns_context:
                    await session.context.close()
                else:
                    await session.page.close()
                    await self._close_profile_if_unused(session)
            except PlaywrightError:
                logger.warning("browser_context_close_failed", session_id=str(session_id))
        async with self._engine.begin() as conn:
            await BrowserSessionsController(conn).set(session_id, status="closed")

    async def _close_profile_if_unused(self, session: Session) -> None:
        # Closing the persistent context flushes cookies and storage to the profile directory.
        still_used = any(s.context is session.context for s in self._sessions.values())
        if not still_used and self._auth_contexts.get(session.user_id) is session.context:
            del self._auth_contexts[session.user_id]
            await session.context.close()

    def _adopt(self, session: Session, page: Page) -> None:
        # A click that opens a new tab moves the session to it.
        session.page = page
        session.elements.clear()
        self._watch(session, page)

    def _on_navigated(self, session: Session, parent: object) -> None:
        if parent is None:  # main frame only
            session.elements.clear()

    async def _guard_route(self, route: Route) -> None:
        host = urlsplit(route.request.url).hostname
        scheme = urlsplit(route.request.url).scheme
        if scheme in ("data", "blob") or (host and await self._guard.allows(host)):
            await route.continue_()
            return
        logger.warning("browser_request_blocked", host=host)
        await route.abort("blockedbyclient")

    # -- facts for classification -------------------------------------------------------

    def facts(self, session_id: uuid.UUID, element_id: str | None = None) -> BrowserFacts:
        session = self._sessions.get(session_id)
        if session is None:
            return BrowserFacts()
        name = session.elements.get(element_id) if element_id else None
        return BrowserFacts(
            context=session.context_kind, domain=domain_of(session.page.url), element_name=name
        )

    async def mode(self, session_id: uuid.UUID) -> str:
        async with self._engine.connect() as conn:
            row = await BrowserSessionsController(conn).get(session_id)
        return str(row["mode"]) if row else "agent"

    # -- agent actions ------------------------------------------------------------------

    async def navigate(self, session: Session, url: str) -> dict[str, Any]:
        try:
            target = validate_url(url)
        except BlockedURL as exc:
            raise BrowserActionError(str(exc)) from exc
        host = urlsplit(target).hostname or ""
        if not await self._guard.allows(host):
            raise BrowserActionError(f"{host} is not a public internet address")
        async with session.lock:
            try:
                await session.page.goto(
                    target, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
                )
            except PlaywrightError as exc:
                raise BrowserActionError(f"navigation failed: {_short(exc)}") from exc
            return await self._after_action(session)

    async def snapshot(self, session: Session) -> dict[str, Any]:
        async with session.lock:
            try:
                data = await take_snapshot(session.page)
            except PlaywrightError as exc:
                raise BrowserActionError(f"snapshot failed: {_short(exc)}") from exc
            session.elements = {e["id"]: e["name"] for e in data["elements"]}
            return {
                "url": session.page.url,
                "title": await session.page.title(),
                "context": session.context_kind,
                "classification": self._classification(session).value,
                "elements": data["elements"],
                "text": data["text"],
            }

    async def click(self, session: Session, element_id: str) -> dict[str, Any]:
        async with session.lock:
            locator = self._element(session, element_id)
            try:
                await locator.click(timeout=ACTION_TIMEOUT_MS)
                await session.page.wait_for_load_state(
                    "domcontentloaded", timeout=ACTION_TIMEOUT_MS
                )
            except PlaywrightError as exc:
                raise BrowserActionError(f"click failed: {_short(exc)}") from exc
            return await self._after_action(session)

    async def fill(self, session: Session, element_id: str, text: str) -> dict[str, Any]:
        async with session.lock:
            try:
                await self._element(session, element_id).fill(text, timeout=ACTION_TIMEOUT_MS)
            except PlaywrightError as exc:
                raise BrowserActionError(f"fill failed: {_short(exc)}") from exc
            return await self._after_action(session)

    async def press(self, session: Session, element_id: str, key: str) -> dict[str, Any]:
        if not KEY_NAME.fullmatch(key):
            raise BrowserActionError(f"unsupported key {key!r}")
        async with session.lock:
            try:
                await self._element(session, element_id).press(key, timeout=ACTION_TIMEOUT_MS)
                await session.page.wait_for_load_state(
                    "domcontentloaded", timeout=ACTION_TIMEOUT_MS
                )
            except PlaywrightError as exc:
                raise BrowserActionError(f"press failed: {_short(exc)}") from exc
            return await self._after_action(session)

    async def scroll(self, session: Session, direction: str) -> dict[str, Any]:
        async with session.lock:
            await session.page.mouse.wheel(0, 700 if direction == "down" else -700)
            await asyncio.sleep(0.3)
            return await self._after_action(session)

    async def screenshot(self, session: Session, owner: SessionOwner) -> dict[str, Any]:
        async with session.lock:
            png = await session.page.screenshot(type="png")
        artifact = await self._artifacts.put(
            user_id=owner.user_id,
            conversation_id=owner.conversation_id,
            topic_id=owner.topic_id,
            kind="screenshot",
            name=f"screenshot-{session.id.hex[:8]}.png",
            data=png,
            classification=self._classification(session),
        )
        return {"artifact_id": str(artifact.id), "bytes": artifact.size, "url": session.page.url}

    async def download(
        self, session: Session, element_id: str, owner: SessionOwner
    ) -> dict[str, Any]:
        async with session.lock:
            locator = self._element(session, element_id)
            try:
                async with session.page.expect_download(timeout=NAVIGATION_TIMEOUT_MS) as info:
                    await locator.click(timeout=ACTION_TIMEOUT_MS)
                download = await info.value
                path = await download.path()
                data = await asyncio.to_thread(path.read_bytes)
            except PlaywrightError as exc:
                raise BrowserActionError(f"download failed: {_short(exc)}") from exc
        artifact = await self._artifacts.put(
            user_id=owner.user_id,
            conversation_id=owner.conversation_id,
            topic_id=owner.topic_id,
            kind="download",
            name=download.suggested_filename or "download",
            data=data,
            classification=self._classification(session),
        )
        return {"artifact_id": str(artifact.id), "name": artifact.name, "bytes": artifact.size}

    # -- human control ------------------------------------------------------------------

    async def human_input(self, session_id: uuid.UUID, action: dict[str, Any]) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise BrowserActionError("browser session is not open")
        kind = action["kind"]
        if kind == "navigate":
            return await self.navigate(session, str(action.get("url") or ""))
        async with session.lock:
            page = session.page
            try:
                if kind == "click" and action.get("x") is not None and action.get("y") is not None:
                    await page.mouse.click(int(action["x"]), int(action["y"]))
                elif kind == "type" and action.get("text"):
                    await page.keyboard.type(str(action["text"]))
                elif kind == "press" and KEY_NAME.fullmatch(str(action.get("key") or "")):
                    await page.keyboard.press(str(action["key"]))
                elif kind == "scroll":
                    await page.mouse.wheel(0, 700 if action.get("direction") != "up" else -700)
                else:
                    raise BrowserActionError("incomplete human input")
                await asyncio.sleep(0.4)
            except PlaywrightError as exc:
                raise BrowserActionError(f"input failed: {_short(exc)}") from exc
            session.elements.clear()
            return await self._after_action(session)

    # -- helpers ------------------------------------------------------------------------

    def get(self, session_id: uuid.UUID) -> Session | None:
        session = self._sessions.get(session_id)
        return session if session and not session.page.is_closed() else None

    def _element(self, session: Session, element_id: str) -> Any:
        if not ELEMENT_ID.fullmatch(element_id) or element_id not in session.elements:
            raise BrowserActionError(
                f"unknown or stale element id {element_id!r}; take a new snapshot"
            )
        return session.page.locator(element_selector(element_id))

    def _classification(self, session: Session) -> DataClassification:
        if session.context_kind == "authenticated":
            return DataClassification.AUTHENTICATED
        return DataClassification.PUBLIC

    async def _after_action(self, session: Session) -> dict[str, Any]:
        url = session.page.url
        title = await session.page.title()
        try:
            jpeg = await session.page.screenshot(type="jpeg", quality=FRAME_QUALITY)
        except PlaywrightError:
            return {"url": url, "title": title}
        async with self._engine.begin() as conn:
            version = await BrowserSessionsController(conn).save_frame(session.id, jpeg, url)
        if self._publisher:
            await self._publisher.publish(
                browser_channel(session.id),
                "browser.frame",
                {"session_id": str(session.id), "frame_version": version, "url": url},
            )
        return {"url": url, "title": title}


def _short(exc: Exception) -> str:
    return str(exc).splitlines()[0][:200]
