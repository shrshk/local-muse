"""notifications: approval_id and Telegram delivery columns

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("approval_id", postgresql.UUID(as_uuid=True)))
    op.add_column("notifications", sa.Column("telegram_status", sa.Text()))
    op.add_column("notifications", sa.Column("telegram_chat_id", sa.BigInteger()))
    op.add_column("notifications", sa.Column("telegram_message_id", sa.BigInteger()))
    op.create_index(
        "ix_notifications_telegram_pending",
        "notifications",
        ["created_at"],
        postgresql_where=sa.text("telegram_status IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_telegram_pending", table_name="notifications")
    op.drop_column("notifications", "telegram_message_id")
    op.drop_column("notifications", "telegram_chat_id")
    op.drop_column("notifications", "telegram_status")
    op.drop_column("notifications", "approval_id")
