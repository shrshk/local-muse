"""Minimal Telegram Bot API client. Outbound HTTPS only; no webhook, no public URL."""

from typing import Any

import httpx

from muse.shared.settings import Settings


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http
        self._base = f"{settings.telegram_api_base.rstrip('/')}/bot{settings.telegram_bot_token}"
        self._poll_timeout = settings.telegram_poll_timeout_s

    async def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": self._poll_timeout}
        if offset is not None:
            params["offset"] = offset
        result = await self._call(
            "getUpdates", params, http_timeout=self._poll_timeout + 10, method="GET"
        )
        updates: list[dict[str, Any]] = result
        return updates

    async def send_message(
        self, chat_id: int, text: str, buttons: list[list[dict[str, str]]] | None = None
    ) -> int:
        body: dict[str, Any] = {"chat_id": chat_id, "text": text[:4000]}
        if buttons:
            body["reply_markup"] = {"inline_keyboard": buttons}
        result = await self._call("sendMessage", body)
        message_id: int = result["message_id"]
        return message_id

    async def answer_callback(self, callback_id: str, text: str) -> None:
        await self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def edit_text(self, chat_id: int, message_id: int, text: str) -> None:
        """Replaces the text and drops the buttons."""
        await self._call(
            "editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text[:4000]}
        )

    async def _call(
        self, name: str, payload: dict[str, Any], http_timeout: float = 15, method: str = "POST"
    ) -> Any:
        url = f"{self._base}/{name}"
        try:
            if method == "GET":
                response = await self._http.get(url, params=payload, timeout=http_timeout)
            else:
                response = await self._http.post(url, json=payload, timeout=http_timeout)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never include the URL: it contains the bot token.
            raise TelegramError(f"{name} failed ({type(exc).__name__})") from exc
        if not body.get("ok"):
            raise TelegramError(f"{name} refused: {str(body.get('description'))[:120]}")
        return body["result"]
