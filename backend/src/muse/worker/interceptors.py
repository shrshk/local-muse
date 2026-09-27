"""Heartbeats for long activities, so a dead worker is noticed in ~heartbeat_timeout, not
start_to_close (10 minutes for a model call)."""

import asyncio
import contextlib
from typing import Any

from temporalio import activity
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
)

HEARTBEAT_EVERY_SECONDS = 10.0


class HeartbeatInterceptor(Interceptor):
    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _HeartbeatingInbound(next)


class _HeartbeatingInbound(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        beat = asyncio.create_task(_heartbeat_forever())
        try:
            return await super().execute_activity(input)
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat


async def _heartbeat_forever() -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_EVERY_SECONDS)
        activity.heartbeat()
