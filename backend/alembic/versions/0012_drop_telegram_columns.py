"""notifications: drop Telegram delivery columns (Telegram removed; mobile push adds its own)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_notifications_telegram_pending", table_name="notifications")
    op.drop_column("notifications", "telegram_message_id")
    op.drop_column("notifications", "telegram_chat_id")
    op.drop_column("notifications", "telegram_status")


def downgrade() -> None:
    op.add_column("notifications", sa.Column("telegram_status", sa.Text()))
    op.add_column("notifications", sa.Column("telegram_chat_id", sa.BigInteger()))
    op.add_column("notifications", sa.Column("telegram_message_id", sa.BigInteger()))
    op.create_index(
        "ix_notifications_telegram_pending",
        "notifications",
        ["created_at"],
        postgresql_where=sa.text("telegram_status IS NULL"),
    )
