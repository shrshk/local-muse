import pytest

from muse.tools.errors import ToolExecutionError
from muse.tools.executors.clock import ClockNowArgs, now
from tests.fakes import NO_SERVICES, make_ctx


async def test_now_in_timezone():
    out = await now(ClockNowArgs(timezone="Asia/Tokyo"), make_ctx(), NO_SERVICES)
    assert isinstance(out, dict)
    assert out["timezone"] == "Asia/Tokyo"
    assert str(out["iso"]).endswith("+09:00")


async def test_unknown_timezone_is_a_tool_error():
    with pytest.raises(ToolExecutionError, match="unknown timezone"):
        await now(ClockNowArgs(timezone="Mars/Olympus"), make_ctx(), NO_SERVICES)
