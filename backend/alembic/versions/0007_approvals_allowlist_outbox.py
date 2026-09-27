"""approvals, domain_allowlist, outbox (demo external-write target)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", UUID, primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("action_id", UUID, sa.ForeignKey("actions.action_id"), nullable=False),
        sa.Column("approval_key", sa.Text(), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("topic_id", UUID),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("destination", sa.Text()),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.Text()),
        sa.Column("channel", sa.Text()),
        sa.Column("decided_at", TS),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("consumed_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_approvals_key_workflow", "approvals", ["approval_key", "workflow_id"])
    op.create_index("ix_approvals_user_status", "approvals", ["user_id", "status"])
    op.create_table(
        "domain_allowlist",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("user_id", "domain", "context", name="pk_domain_allowlist"),
    )
    op.create_table(
        "outbox",
        sa.Column("action_id", UUID, primary_key=True),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("recipient", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("outbox")
    op.drop_table("domain_allowlist")
    op.drop_table("approvals")
