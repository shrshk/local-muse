"""profile.remember: stores a long-lived fact about the user in profile memory."""

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from muse.modules.memory.memory_controller import ProfileMemoryController
from muse.modules.memory.memory_handler import InvalidFact, validate_fact
from muse.modules.memory.memory_schema import KEY_PATTERN
from muse.tools.errors import ToolExecutionError
from muse.tools.schema import ExecContext, ToolServices


class RememberArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=KEY_PATTERN, description="Short snake_case name, e.g. home_city")
    value: str = Field(min_length=1, max_length=500, description="The fact, in plain words")


async def remember(args: RememberArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    try:
        validate_fact(args.key, args.value)
    except InvalidFact as exc:
        raise ToolExecutionError(str(exc)) from exc
    async with services.engine.begin() as conn:
        fact = await ProfileMemoryController(conn).put(ctx.user_id, args.key, args.value, "agent")
    return {"remembered": fact.key}
