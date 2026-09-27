"""browser_sessions, browser_frames

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "browser_sessions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("topic_id", UUID),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False, server_default=sa.text("'agent'")),
        sa.Column("current_url", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("frame_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_browser_sessions_conversation", "browser_sessions", ["conversation_id"])
    op.create_table(
        "browser_frames",
        sa.Column(
            "session_id",
            UUID,
            sa.ForeignKey("browser_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("jpeg", postgresql.BYTEA(), nullable=False),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("browser_frames")
    op.drop_table("browser_sessions")
