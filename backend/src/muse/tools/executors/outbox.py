"""outbox.send: the demo EXTERNAL_WRITE tool. It "sends" by recording the message in the outbox
table; no real delivery. Idempotent on action_id, like any real external executor must be."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, JsonValue
from sqlalchemy.dialects.postgresql import insert

from muse.shared.tables import outbox
from muse.tools.errors import ToolExecutionError
from muse.tools.schema import ExecContext, ToolServices


class SendArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: EmailStr
    body: str = Field(min_length=1, max_length=5000)


async def send(args: SendArgs, ctx: ExecContext, services: ToolServices) -> JsonValue:
    if ctx.action_id is None:
        raise ToolExecutionError("send requires an action id")
    async with services.engine.begin() as conn:
        stmt = insert(outbox).values(
            action_id=ctx.action_id,
            user_id=ctx.user_id,
            conversation_id=ctx.conversation_id,
            recipient=str(args.recipient),
            body=args.body,
        )
        await conn.execute(stmt.on_conflict_do_nothing(index_elements=[outbox.c.action_id]))
    return {"sent": True, "recipient": str(args.recipient), "outbox_id": str(ctx.action_id)}
