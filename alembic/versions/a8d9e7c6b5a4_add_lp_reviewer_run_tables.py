"""add lp reviewer run tables

Revision ID: a8d9e7c6b5a4
Revises: f9c1a2b3d4e5
Create Date: 2026-08-02 14:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8d9e7c6b5a4"
down_revision: Union[str, Sequence[str], None] = "f9c1a2b3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lp_reviewer_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requested_lp_documents_id", sa.Uuid(), nullable=False),
        sa.Column("resolved_lp_documents_id", sa.Uuid(), nullable=False),
        sa.Column("resolved_document_name", sa.String(length=512), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="processing"
        ),
        sa.Column("aggregate_verdict", sa.String(length=32), nullable=True),
        sa.Column("aggregate_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["resolved_lp_documents_id"],
            ["lp_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lp_reviewer_run_requested_lp_documents_id",
        "lp_reviewer_run",
        ["requested_lp_documents_id"],
    )
    op.create_index(
        "ix_lp_reviewer_run_resolved_lp_documents_id",
        "lp_reviewer_run",
        ["resolved_lp_documents_id"],
    )
    op.create_index("ix_lp_reviewer_run_status", "lp_reviewer_run", ["status"])

    op.create_table(
        "lp_reviewer_page_result",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reviewer_run_id", sa.Uuid(), nullable=False),
        sa.Column("lp_documents_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.String(length=64), nullable=False),
        sa.Column("review_error", sa.Text(), nullable=True),
        sa.Column(
            "extracted_text_char_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("strengths", sa.JSON(), nullable=True),
        sa.Column("issues", sa.JSON(), nullable=True),
        sa.Column("recommendations", sa.JSON(), nullable=True),
        sa.Column("verdict", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_run_id"], ["lp_reviewer_run.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["lp_documents_id"], ["lp_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lp_reviewer_page_result_reviewer_run_id",
        "lp_reviewer_page_result",
        ["reviewer_run_id"],
    )
    op.create_index(
        "ix_lp_reviewer_page_result_lp_documents_id",
        "lp_reviewer_page_result",
        ["lp_documents_id"],
    )
    op.create_index(
        "ix_lp_reviewer_page_result_review_status",
        "lp_reviewer_page_result",
        ["review_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lp_reviewer_page_result_review_status",
        table_name="lp_reviewer_page_result",
    )
    op.drop_index(
        "ix_lp_reviewer_page_result_lp_documents_id",
        table_name="lp_reviewer_page_result",
    )
    op.drop_index(
        "ix_lp_reviewer_page_result_reviewer_run_id",
        table_name="lp_reviewer_page_result",
    )
    op.drop_table("lp_reviewer_page_result")

    op.drop_index("ix_lp_reviewer_run_status", table_name="lp_reviewer_run")
    op.drop_index(
        "ix_lp_reviewer_run_resolved_lp_documents_id",
        table_name="lp_reviewer_run",
    )
    op.drop_index(
        "ix_lp_reviewer_run_requested_lp_documents_id",
        table_name="lp_reviewer_run",
    )
    op.drop_table("lp_reviewer_run")
