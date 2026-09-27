"""goals, notifications

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", UUID, primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text()),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("fire_at", TS),
        sa.Column("every_minutes", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("last_value", sa.Text()),
        sa.Column("last_condition", sa.Boolean()),
        sa.Column("last_summary", sa.Text()),
        sa.Column("last_run_at", TS),
        sa.Column("next_run_at", TS),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("notify_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_goals_user_status", "goals", ["user_id", "status"])
    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", UUID),
        sa.Column("goal_id", UUID),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", TS),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("goals")
