"""Web push: interruption budget, endpoint allowlist, content-free encrypted payloads."""

import base64
import json
import os

import http_ece
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from muse.modules.notifications.budget import (
    Importance,
    Level,
    Preference,
    apply_feedback,
    preference_for,
    should_push,
)
from muse.modules.push.sender import (
    EndpointNotAllowed,
    PushGone,
    PushSender,
    Target,
    VapidKey,
    endpoint_allowed,
)
from muse.shared.settings import Settings

APPLE = "https://web.push.apple.com/QH8-abc"


def settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("endpoint", "allowed"),
    [
        (APPLE, True),
        ("https://fcm.googleapis.com/fcm/send/xyz", True),
        ("https://db5p.notify.windows.com/w/?token=1", True),
        ("http://web.push.apple.com/x", False),  # plain http
        ("https://sandboxd:8080/sandboxes", False),  # internal service
        ("https://host.docker.internal:11434/api", False),
        ("https://user:pw@web.push.apple.com/x", False),  # userinfo
        ("https://web.push.apple.com.evil.example/x", False),
        ("ftp://web.push.apple.com/x", False),
    ],
)
def test_only_known_push_services_over_https(endpoint: str, allowed: bool):
    assert endpoint_allowed(endpoint, settings()) is allowed


def test_http_only_for_hosts_tests_add():
    test = settings(push_allow_http=True, push_allowed_hosts="push-mock")
    assert endpoint_allowed("http://push-mock:8082/p/1", test)
    assert not endpoint_allowed("http://sandboxd:8080/", test)


GOAL_ALL = Preference(kind="goal", level=Level.ALL, daily_cap=2)


def test_approvals_always_push_even_when_muted():
    muted = Preference(kind="approval", level=Level.NONE, daily_cap=0)
    assert should_push("approval", Importance.NORMAL, muted, pushed_today=99)


def test_levels_and_daily_cap():
    assert should_push("goal", Importance.NORMAL, GOAL_ALL, pushed_today=1)
    assert not should_push("goal", Importance.NORMAL, GOAL_ALL, pushed_today=2), "cap reached"
    important = GOAL_ALL.model_copy(update={"level": Level.IMPORTANT})
    assert not should_push("goal", Importance.NORMAL, important, pushed_today=0)
    assert should_push("goal", Importance.HIGH, important, pushed_today=0)
    none = GOAL_ALL.model_copy(update={"level": Level.NONE})
    assert not should_push("goal", Importance.HIGH, none, pushed_today=0)


def test_feedback_moves_one_level_and_none_mutes():
    assert apply_feedback(GOAL_ALL, "less").level is Level.IMPORTANT
    assert apply_feedback(GOAL_ALL, "more").level is Level.ALL, "already loudest"
    quiet = GOAL_ALL.model_copy(update={"level": Level.NONE})
    assert apply_feedback(quiet, "more").level is Level.IMPORTANT
    assert apply_feedback(GOAL_ALL, "none").level is Level.NONE


def test_defaults_per_kind():
    assert preference_for("goal", None).level is Level.ALL
    assert preference_for("idea", None).level is Level.IMPORTANT
    unknown = preference_for("weather", None)
    assert unknown.kind == "weather" and unknown.level is Level.IMPORTANT


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def subscriber() -> tuple[ec.EllipticCurvePrivateKey, bytes, Target]:
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = os.urandom(16)
    return key, auth, Target(APPLE, _b64(public), _b64(auth))


async def test_push_is_encrypted_signed_and_carries_only_the_id():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    key, auth, target = subscriber()
    vapid = VapidKey(VapidKey.generate_pem())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await PushSender(http, vapid, settings()).send(
            target, {"id": "n-1"}, ttl=60, urgency="high"
        )

    (request,) = seen
    assert request.headers["authorization"].startswith("vapid t=")
    assert f"k={vapid.public_key}" in request.headers["authorization"]
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["ttl"] == "60" and request.headers["urgency"] == "high"
    assert b"n-1" not in request.content, "the body is encrypted"
    plain = http_ece.decrypt(
        request.content, private_key=key, auth_secret=auth, version="aes128gcm"
    )
    assert json.loads(plain) == {"id": "n-1"}


async def test_gone_subscriptions_and_disallowed_endpoints():
    calls = 0

    def gone(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(410)

    _, _, target = subscriber()
    vapid = VapidKey(VapidKey.generate_pem())
    async with httpx.AsyncClient(transport=httpx.MockTransport(gone)) as http:
        sender = PushSender(http, vapid, settings())
        with pytest.raises(PushGone):
            await sender.send(target, {"id": "n"}, ttl=60, urgency="normal")
        internal = Target("https://sandboxd:8080/x", target.p256dh, target.auth)
        with pytest.raises(EndpointNotAllowed):
            await sender.send(internal, {"id": "n"}, ttl=60, urgency="normal")
    assert calls == 1, "a disallowed endpoint is never contacted"
