"""Sends one Web Push message (RFC 8291 encryption, RFC 8292 VAPID) with httpx.

The payload is only a notification id; the service worker fetches the text from the Mac. Push
services (Apple, Google, ...) see that a push happened, never what it is about.
"""

import base64
import fnmatch
import json
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02
from pywebpush import WebPusher

from muse.shared.settings import Settings

VAPID_TTL_SECONDS = 12 * 3600
SEND_TIMEOUT_SECONDS = 10.0


class PushError(Exception):
    """Delivery failed; worth retrying another time."""


class PushGone(PushError):
    """The push service says the subscription no longer exists (404/410)."""


class EndpointNotAllowed(PushError):
    """The endpoint is not a known push service."""


def endpoint_allowed(endpoint: str, settings: Settings) -> bool:
    parts = urlsplit(endpoint)
    schemes = {"https", "http"} if settings.push_allow_http else {"https"}
    if parts.scheme not in schemes or not parts.hostname or parts.username or parts.password:
        return False
    hosts = [h.strip() for h in settings.push_allowed_hosts.split(",") if h.strip()]
    return any(fnmatch.fnmatchcase(parts.hostname, pattern) for pattern in hosts)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class VapidKey:
    """The server's signing key. Browsers bind each subscription to its public half."""

    def __init__(self, pem: str) -> None:
        self._vapid = Vapid02.from_pem(pem.encode())

    @staticmethod
    def generate_pem() -> str:
        vapid = Vapid02()
        vapid.generate_keys()
        pem: bytes = vapid.private_pem()
        return pem.decode()

    @property
    def public_key(self) -> str:
        raw = self._vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return _b64url(raw)

    def headers(self, endpoint: str, subject: str) -> dict[str, str]:
        parts = urlsplit(endpoint)
        claims = {
            "sub": subject,
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int(time.time()) + VAPID_TTL_SECONDS,
        }
        signed: dict[str, str] = self._vapid.sign(claims)
        return signed


@dataclass(frozen=True)
class Target:
    endpoint: str
    p256dh: str
    auth: str


class PushSender:
    def __init__(self, http: httpx.AsyncClient, key: VapidKey, settings: Settings) -> None:
        self._http = http
        self._key = key
        self._settings = settings

    async def send(self, target: Target, payload: dict[str, str], ttl: int, urgency: str) -> None:
        if not endpoint_allowed(target.endpoint, self._settings):
            raise EndpointNotAllowed("endpoint is not an allowed push service")
        info = {"endpoint": target.endpoint, "keys": {"p256dh": target.p256dh, "auth": target.auth}}
        body = WebPusher(info).encode(json.dumps(payload).encode(), "aes128gcm")["body"]
        headers = self._key.headers(target.endpoint, self._settings.push_vapid_subject)
        headers |= {
            "TTL": str(ttl),
            "Urgency": urgency,
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
        }
        try:
            response = await self._http.post(
                target.endpoint,
                content=body,
                headers=headers,
                timeout=SEND_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            # The endpoint URL is a capability; keep it out of the error text.
            raise PushError(type(exc).__name__) from None
        if response.status_code in (404, 410):
            raise PushGone(str(response.status_code))
        if response.status_code >= 300:
            raise PushError(str(response.status_code))
