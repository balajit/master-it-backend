"""Add lp_book_process table for BookPipeline tracking

Revision ID: f1a2b3c4d5e6
Revises: b3c2d4e5f6a7
Create Date: 2026-07-29 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "b3c2d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lp_book_process",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
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
    op.create_index(
        "ix_lp_book_process_document_id", "lp_book_process", ["document_id"]
    )
    op.create_index("ix_lp_book_process_status", "lp_book_process", ["status"])


def downgrade() -> None:
    op.drop_index("ix_lp_book_process_status", table_name="lp_book_process")
    op.drop_index("ix_lp_book_process_document_id", table_name="lp_book_process")
    op.drop_table("lp_book_process")
