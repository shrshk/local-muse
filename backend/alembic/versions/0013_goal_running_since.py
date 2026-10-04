"""goals: running_since, set while a check runs (progress in the Goals tab)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("goals", sa.Column("running_since", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("goals", "running_since")
