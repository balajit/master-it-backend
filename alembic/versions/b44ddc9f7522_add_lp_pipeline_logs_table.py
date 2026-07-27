"""add lp_pipeline_logs table

Revision ID: b44ddc9f7522
Revises: b2c3d4e5f6a7
Create Date: 2026-07-27 07:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b44ddc9f7522"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lp_pipeline_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("stage", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("output", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("result", sa.String(length=16), nullable=False, server_default="success"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("lp_pipeline_logs")
