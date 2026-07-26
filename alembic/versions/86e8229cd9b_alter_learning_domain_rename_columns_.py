"""alter learning domain: rename columns, add progress tables

Revision ID: 86e8229cd9b
Revises: d47d494bd230
Create Date: 2026-07-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "86e8229cd9b"
down_revision: Union[str, Sequence[str], None] = "d47d494bd230"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Rename practice_activities → practices ──────────────────────────────
    op.rename_table("practice_activities", "practices")
    # Rename order → display_order on practices
    with op.batch_alter_table("practices") as batch_op:
        batch_op.alter_column("order", new_column_name="display_order")
    # Add new columns required by the new schema
    op.add_column(
        "practices",
        sa.Column("required_correct", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "practices",
        sa.Column("total_questions", sa.Integer(), nullable=False, server_default="0"),
    )
    # Drop columns no longer needed
    with op.batch_alter_table("practices") as batch_op:
        batch_op.drop_column("description")
        batch_op.drop_column("activity_type")
        batch_op.drop_column("content")

    # ── Units: rename order → display_order ────────────────────────────────
    with op.batch_alter_table("units") as batch_op:
        batch_op.alter_column("order", new_column_name="display_order")

    # ── Sections: rename order → display_order, replace description with estimated_minutes ──
    with op.batch_alter_table("sections") as batch_op:
        batch_op.alter_column("order", new_column_name="display_order")
        batch_op.drop_column("description")
    op.add_column(
        "sections",
        sa.Column(
            "estimated_minutes", sa.Integer(), nullable=False, server_default="0"
        ),
    )

    # ── Lessons: rename order → display_order, rename content → description, add duration_minutes ──
    with op.batch_alter_table("lessons") as batch_op:
        batch_op.alter_column("order", new_column_name="display_order")
    # Rename content → description: add new column, copy data, drop old
    op.add_column(
        "lessons",
        sa.Column("description", sa.String(), nullable=False, server_default=""),
    )
    op.execute("UPDATE lessons SET description = content")
    with op.batch_alter_table("lessons") as batch_op:
        batch_op.drop_column("content")
    op.add_column(
        "lessons",
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="0"),
    )

    # ── Quizzes: drop extra columns ────────────────────────────────────────
    with op.batch_alter_table("quizzes") as batch_op:
        batch_op.drop_column("description")
        batch_op.drop_column("questions")
        batch_op.drop_column("passing_score")
        batch_op.drop_column("order")

    # ── New progress tables ────────────────────────────────────────────────
    op.create_table(
        "user_lesson_progress",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column(
            "lesson_id", sa.Integer(), sa.ForeignKey("lessons.id"), primary_key=True
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="NOT_STARTED"),
        sa.Column("completed_at", sa.String(), nullable=True),
    )
    op.create_table(
        "user_practice_progress",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column(
            "practice_id", sa.Integer(), sa.ForeignKey("practices.id"), primary_key=True
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("best_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(), nullable=False, server_default="NOT_STARTED"),
    )
    op.create_table(
        "user_quiz_progress",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column(
            "quiz_id", sa.Integer(), sa.ForeignKey("quizzes.id"), primary_key=True
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
    )


def downgrade() -> None:
    # Drop progress tables
    op.drop_table("user_quiz_progress")
    op.drop_table("user_practice_progress")
    op.drop_table("user_lesson_progress")

    # Restore quizzes columns
    op.add_column(
        "quizzes",
        sa.Column("description", sa.String(), nullable=False, server_default=""),
    )
    op.add_column("quizzes", sa.Column("questions", sa.Text(), nullable=True))
    op.add_column(
        "quizzes",
        sa.Column("passing_score", sa.Integer(), nullable=False, server_default="70"),
    )
    op.add_column(
        "quizzes", sa.Column("order", sa.Integer(), nullable=False, server_default="0")
    )

    # Restore lessons columns
    with op.batch_alter_table("lessons") as batch_op:
        batch_op.drop_column("duration_minutes")
    op.add_column(
        "lessons", sa.Column("content", sa.Text(), nullable=False, server_default="")
    )
    op.execute("UPDATE lessons SET content = description")
    with op.batch_alter_table("lessons") as batch_op:
        batch_op.drop_column("description")
    with op.batch_alter_table("lessons") as batch_op:
        batch_op.alter_column("display_order", new_column_name="order")

    # Restore sections columns
    with op.batch_alter_table("sections") as batch_op:
        batch_op.drop_column("estimated_minutes")
    op.add_column(
        "sections",
        sa.Column("description", sa.String(), nullable=False, server_default=""),
    )
    with op.batch_alter_table("sections") as batch_op:
        batch_op.alter_column("display_order", new_column_name="order")

    # Restore units columns
    with op.batch_alter_table("units") as batch_op:
        batch_op.alter_column("display_order", new_column_name="order")

    # Restore practice_activities
    with op.batch_alter_table("practices") as batch_op:
        batch_op.add_column(
            sa.Column("description", sa.String(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column(
                "activity_type", sa.String(), nullable=False, server_default="exercise"
            )
        )
        batch_op.add_column(sa.Column("content", sa.Text(), nullable=True))
    with op.batch_alter_table("practices") as batch_op:
        batch_op.drop_column("required_correct")
        batch_op.drop_column("total_questions")
        batch_op.alter_column("display_order", new_column_name="order")
    op.rename_table("practices", "practice_activities")
