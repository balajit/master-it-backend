"""Agent lesson progress and completion tracking tables.

Revision ID: e8f9721937fd
Revises: 8d21271740ae
Create Date: 2026-08-06

Changes
-------
1. lp_agent_lesson_progress  — orchestrator tracks lesson-level status
2. lp_agent_lesson_completions — sub-agents write a marker when they finish a lesson
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9721937fd"
down_revision: str | None = "8d21271740ae"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ── lp_agent_lesson_progress ──────────────────────────────────────────────
    op.create_table(
        "lp_agent_lesson_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_process_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("lesson_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("missing_agents", sa.Text(), nullable=True),  # JSON list
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_process_id",
            "lesson_id",
            name="uq_agent_lesson_progress",
        ),
    )
    with op.batch_alter_table("lp_agent_lesson_progress") as batch_op:
        batch_op.create_index(
            "idx_lp_agent_lesson_progress_run",
            ["agent_process_id"],
            unique=False,
        )
        batch_op.create_index(
            "idx_lp_agent_lesson_progress_document_id",
            ["document_id"],
            unique=False,
        )

    # ── lp_agent_lesson_completions ───────────────────────────────────────────
    op.create_table(
        "lp_agent_lesson_completions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_process_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("lesson_id", sa.String(length=36), nullable=False),
        sa.Column("agent_type", sa.String(length=32), nullable=False),
        sa.Column(
            "ran_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_process_id",
            "lesson_id",
            "agent_type",
            name="uq_agent_lesson_completion",
        ),
    )
    with op.batch_alter_table("lp_agent_lesson_completions") as batch_op:
        batch_op.create_index(
            "idx_lp_agent_lesson_completions_run",
            ["agent_process_id", "lesson_id"],
            unique=False,
        )
        batch_op.create_index(
            "idx_lp_agent_lesson_completions_document_id",
            ["document_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("lp_agent_lesson_completions")
    op.drop_table("lp_agent_lesson_progress")
