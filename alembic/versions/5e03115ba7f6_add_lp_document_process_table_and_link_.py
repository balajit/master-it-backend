"""add lp_document_process table and link to pipeline_logs

Revision ID: 5e03115ba7f6
Revises: b44ddc9f7522
Create Date: 2026-07-27 07:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5e03115ba7f6"
down_revision: Union[str, None] = "b44ddc9f7522"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lp_document_process",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("abs_path", sa.String(length=1024), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "lp_pipeline_logs",
        sa.Column(
            "document_process_id",
            sa.Integer(),
            sa.ForeignKey("lp_document_process.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_lp_pipeline_logs_document_process_id",
        "lp_pipeline_logs",
        ["document_process_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lp_pipeline_logs_document_process_id", table_name="lp_pipeline_logs"
    )
    op.drop_column("lp_pipeline_logs", "document_process_id")
    op.drop_table("lp_document_process")
