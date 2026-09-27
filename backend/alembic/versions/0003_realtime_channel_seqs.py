"""realtime_channel_seqs: per-channel event sequence for gap detection

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "realtime_channel_seqs",
        sa.Column("channel", sa.Text(), primary_key=True),
        sa.Column("seq", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("realtime_channel_seqs")
