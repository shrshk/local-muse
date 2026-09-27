"""Keeps the browser on the public internet.

The worker's Chromium shares a network with internal services (Temporal UI, sandboxd, Postgres)
and can reach the host (Ollama). A prompt-injected page must not be able to steer the agent there,
so every request's host must resolve only to globally routable addresses. DNS rebinding between
this check and Chromium's own lookup is a known gap (documented in threat-model.md).
"""

import asyncio
import ipaddress
import socket
import time
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}
CACHE_SECONDS = 60.0


class BlockedURL(ValueError):
    pass


def validate_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedURL(f"only http and https URLs are allowed, not {parts.scheme or 'none'!r}")
    if not parts.hostname:
        raise BlockedURL("URL has no host")
    return parts.geturl()


def domain_of(url: str) -> str | None:
    host = urlsplit(url).hostname
    return host.lower() if host else None


def is_global_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


class HostGuard:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[bool, float]] = {}

    async def allows(self, host: str) -> bool:
        cached = self._cache.get(host)
        if cached and time.monotonic() - cached[1] < CACHE_SECONDS:
            return cached[0]
        allowed = await self._resolve_all_global(host)
        self._cache[host] = (allowed, time.monotonic())
        return allowed

    async def _resolve_all_global(self, host: str) -> bool:
        try:
            ipaddress.ip_address(host)
            return is_global_address(host)
        except ValueError:
            pass
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
        except OSError:
            return False
        addresses = {info[4][0] for info in infos}
        return bool(addresses) and all(is_global_address(str(a)) for a in addresses)
