"""Per-channel event sequence numbers. Allocated in Postgres so restarts never reuse one."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from muse.shared.tables import realtime_channel_seqs


class RealtimeSeqController:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def next(self, channel: str) -> int:
        upsert = insert(realtime_channel_seqs).values(channel=channel, seq=1)
        stmt = upsert.on_conflict_do_update(
            index_elements=[realtime_channel_seqs.c.channel],
            set_={"seq": realtime_channel_seqs.c.seq + 1},
        ).returning(realtime_channel_seqs.c.seq)
        seq: int = (await self._conn.execute(stmt)).scalar_one()
        return seq

    async def current(self, channel: str) -> int:
        stmt = select(realtime_channel_seqs.c.seq).where(realtime_channel_seqs.c.channel == channel)
        seq: int | None = (await self._conn.execute(stmt)).scalar_one_or_none()
        return seq or 0
