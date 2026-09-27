import uuid

import httpx
import pytest

from muse.notifications.telegram_bot import approval_buttons, parse_callback
from muse.notifications.telegram_client import TelegramClient, TelegramError
from muse.shared.settings import Settings, allowed_chat_ids, telegram_enabled

KEY = "ab" * 32


def test_buttons_round_trip_and_fit_telegrams_64_byte_limit():
    approval_id = uuid.uuid4()
    [[approve, deny]] = approval_buttons(approval_id, KEY)
    assert len(approve["callback_data"].encode()) <= 64
    assert parse_callback(approve["callback_data"]) == (approval_id, KEY[:16], True)
    assert parse_callback(deny["callback_data"]) == (approval_id, KEY[:16], False)


@pytest.mark.parametrize(
    "data", ["", "a:not-a-uuid:abc:y", f"a:{uuid.uuid4()}:abc:maybe", f"x:{uuid.uuid4()}:abc:y"]
)
def test_malformed_callbacks_are_rejected(data: str):
    assert parse_callback(data) is None


def test_telegram_is_off_unless_fully_configured():
    assert not telegram_enabled(Settings())
    assert not telegram_enabled(Settings(telegram_bot_token="t", telegram_allowed_chat_ids="1"))
    on = Settings(
        telegram_bot_token="t", telegram_allowed_chat_ids="1, 2", telegram_owner_username="owner"
    )
    assert telegram_enabled(on)
    assert allowed_chat_ids(on) == {1, 2}


async def test_client_errors_never_contain_the_token():
    secret = "123456:SECRET-TOKEN"

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = TelegramClient(
        httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
        Settings(telegram_bot_token=secret),
    )
    with pytest.raises(TelegramError) as caught:
        await client.send_message(1, "hi")
    assert secret not in str(caught.value)


async def test_client_sends_buttons_as_an_inline_keyboard():
    seen: dict[str, object] = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.read()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    client = TelegramClient(
        httpx.AsyncClient(transport=httpx.MockTransport(ok)), Settings(telegram_bot_token="t")
    )
    buttons = approval_buttons(uuid.uuid4(), KEY)
    assert await client.send_message(5, "Approve?", buttons) == 7
    assert seen["path"] == "/bott/sendMessage"
    assert b"inline_keyboard" in seen["body"]  # type: ignore[operator]
