"""clock.now: current time in an IANA timezone."""

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from muse.tools.errors import ToolExecutionError
from muse.tools.schema import ExecContext


class ClockNowArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(default="UTC", description="IANA timezone, e.g. Asia/Tokyo")


async def now(args: ClockNowArgs, ctx: ExecContext) -> JsonValue:
    try:
        zone = ZoneInfo(args.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ToolExecutionError(f"unknown timezone {args.timezone!r}") from exc
    current = dt.datetime.now(zone)
    return {
        "timezone": args.timezone,
        "iso": current.isoformat(timespec="seconds"),
        "weekday": current.strftime("%A"),
    }
