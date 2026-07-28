"""Add item_progress table and lp_book tables migration

Adds item_progress for tracking per-student progress at the lp_book_item level.
Also adds lp_book_chapter, lp_book_lesson, lp_book_page, lp_book_item tables
to the master-it database (these are the same tables added to the LP database
via the LP migration, but here we create them in master-it if the databases
are shared, or skip if they live in the LP SQLite DB only).

Revision ID: c9e2f4a1b7d3
Revises: b2c3d4e5f6a7
Create Date: 2026-07-28 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9e2f4a1b7d3"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "item_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("enrollment_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["enrollment_id"],
            ["course_enrollments.user_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_item_progress_enrollment_id", "item_progress", ["enrollment_id"]
    )
    op.create_index("idx_item_progress_item_id", "item_progress", ["item_id"])


def downgrade() -> None:
    op.drop_index("idx_item_progress_item_id", table_name="item_progress")
    op.drop_index("idx_item_progress_enrollment_id", table_name="item_progress")
    op.drop_table("item_progress")
