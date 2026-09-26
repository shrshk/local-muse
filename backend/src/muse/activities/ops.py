"""Operational activities. A Temporal worker needs at least one registration to poll."""

from temporalio import activity


@activity.defn
async def ping() -> str:
    return "pong"
