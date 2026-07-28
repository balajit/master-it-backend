"""Add lp_book_chapter, lp_book_lesson, lp_book_page, lp_book_item tables

Revision ID: a7f3c1b8e2d9
Revises: 5e03115ba7f6
Create Date: 2026-07-28 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7f3c1b8e2d9"
down_revision: Union[str, None] = "5e03115ba7f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lp_book_chapter",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["lp_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lp_book_chapter_document_id", "lp_book_chapter", ["document_id"]
    )
    op.create_index("ix_lp_book_chapter_unit_id", "lp_book_chapter", ["unit_id"])

    op.create_table(
        "lp_book_lesson",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["chapter_id"], ["lp_book_chapter.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lp_book_lesson_chapter_id", "lp_book_lesson", ["chapter_id"])
    op.create_index("ix_lp_book_lesson_unit_id", "lp_book_lesson", ["unit_id"])

    op.create_table(
        "lp_book_page",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lp_book_lesson.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lp_book_page_lesson_id", "lp_book_page", ["lesson_id"])

    op.create_table(
        "lp_book_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False, server_default="text"),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("style", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["page_id"], ["lp_book_page.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lp_book_item_page_id", "lp_book_item", ["page_id"])


def downgrade() -> None:
    op.drop_table("lp_book_item")
    op.drop_table("lp_book_page")
    op.drop_table("lp_book_lesson")
    op.drop_table("lp_book_chapter")
