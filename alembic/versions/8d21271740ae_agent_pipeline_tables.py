"""Agent pipeline tables + lp_ table renames.

Revision ID: 8d21271740ae
Revises: b6c7d8e9f0a1
Create Date: 2026-08-06

Changes
-------
1. Rename existing app tables to lp_ prefix (create-copy-drop pattern):
   flashcards            → lp_flashcards
   quizzes               → lp_quizzes
   practices             → lp_practices
   user_practice_progress → lp_user_practice_progress
   user_quiz_progress    → lp_user_quiz_progress
   user_flashcards       → lp_user_flashcards
   user_flashcards_request → lp_user_flashcards_request

2. Add new Agent Pipeline (Pipeline 3) tables:
   lp_agent_process
   lp_keywords
   lp_summaries
   lp_quiz_questions
   lp_practice_questions
   lp_agent_flashcards
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d21271740ae"
down_revision: str | None = "b6c7d8e9f0a1"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ── 1. Rename: flashcards → lp_flashcards ────────────────────────────────
    op.create_table(
        "lp_flashcards",
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("state", sa.Integer(), nullable=False),
        sa.Column("stability", sa.Float(), nullable=False),
        sa.Column("difficulty", sa.Float(), nullable=False),
        sa.Column("elapsed_days", sa.Integer(), nullable=False),
        sa.Column("scheduled_days", sa.Integer(), nullable=False),
        sa.Column("due", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("card_id"),
    )
    op.execute("INSERT INTO lp_flashcards SELECT * FROM flashcards")
    op.drop_table("flashcards")

    # ── 2. Rename: quizzes → lp_quizzes ──────────────────────────────────────
    op.create_table(
        "lp_quizzes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lp_quizzes") as batch_op:
        batch_op.create_index("idx_lp_quizzes_section_id", ["section_id"], unique=False)
    op.execute("INSERT INTO lp_quizzes SELECT * FROM quizzes")

    # ── 3. Rename: practices → lp_practices ──────────────────────────────────
    op.create_table(
        "lp_practices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("required_correct", sa.Integer(), nullable=False),
        sa.Column("total_questions", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("practice_type", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lp_practices") as batch_op:
        batch_op.create_index(
            "idx_lp_practices_section_id", ["section_id", "display_order"], unique=False
        )
    op.execute("INSERT INTO lp_practices SELECT * FROM practices")

    # ── 4. Rename: user_quiz_progress → lp_user_quiz_progress ────────────────
    # Must be done before dropping quizzes (FK dep), but quizzes already copied.
    op.create_table(
        "lp_user_quiz_progress",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["quiz_id"], ["lp_quizzes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "quiz_id"),
    )
    op.execute("INSERT INTO lp_user_quiz_progress SELECT * FROM user_quiz_progress")
    op.drop_table("user_quiz_progress")

    # ── 5. Rename: user_practice_progress → lp_user_practice_progress ────────
    op.create_table(
        "lp_user_practice_progress",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("practice_id", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("best_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["practice_id"], ["lp_practices.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "practice_id"),
    )
    op.execute(
        "INSERT INTO lp_user_practice_progress SELECT * FROM user_practice_progress"
    )
    op.drop_table("user_practice_progress")

    # Now safe to drop original quizzes/practices
    with op.batch_alter_table("quizzes") as batch_op:
        batch_op.drop_index("idx_quizzes_section_id")
    op.drop_table("quizzes")

    with op.batch_alter_table("practices") as batch_op:
        batch_op.drop_index("idx_practices_section_id")
    op.drop_table("practices")

    # ── 6. Rename: user_flashcards → lp_user_flashcards ──────────────────────
    op.create_table(
        "lp_user_flashcards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("lesson_id", sa.Uuid(), nullable=True),
        sa.Column("is_generated", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lp_user_flashcards") as batch_op:
        batch_op.create_index(
            "idx_lp_user_flashcards_course_id", ["course_id"], unique=False
        )
        batch_op.create_index(
            "idx_lp_user_flashcards_created_by", ["created_by"], unique=False
        )
        batch_op.create_index(
            "idx_lp_user_flashcards_lesson_id", ["lesson_id"], unique=False
        )
        batch_op.create_index(
            "idx_lp_user_flashcards_unit_id", ["unit_id"], unique=False
        )
        batch_op.create_index(
            "idx_lp_user_flashcards_user_id", ["user_id"], unique=False
        )
    op.execute("INSERT INTO lp_user_flashcards SELECT * FROM user_flashcards")
    with op.batch_alter_table("user_flashcards") as batch_op:
        batch_op.drop_index("idx_user_flashcards_user_id")
        batch_op.drop_index("idx_user_flashcards_unit_id")
        batch_op.drop_index("idx_user_flashcards_lesson_id")
        batch_op.drop_index("idx_user_flashcards_created_by")
        batch_op.drop_index("idx_user_flashcards_course_id")
    op.drop_table("user_flashcards")

    # ── 7. Rename: user_flashcards_request → lp_user_flashcards_request ──────
    op.create_table(
        "lp_user_flashcards_request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lp_user_flashcards_request") as batch_op:
        batch_op.create_index(
            "ix_lp_user_flashcards_request_scope_target",
            ["scope", "target_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_lp_user_flashcards_request_user_id", ["user_id"], unique=False
        )
    op.execute(
        "INSERT INTO lp_user_flashcards_request SELECT * FROM user_flashcards_request"
    )
    with op.batch_alter_table("user_flashcards_request") as batch_op:
        batch_op.drop_index("ix_user_flashcards_request_scope_target")
        batch_op.drop_index("ix_user_flashcards_request_user_id")
        try:
            batch_op.drop_index("uq_user_flashcards_request_active")
        except Exception:
            pass  # SQLite may not support the partial index; skip silently
    op.drop_table("user_flashcards_request")

    # ── 8. New: lp_agent_process ──────────────────────────────────────────────
    op.create_table(
        "lp_agent_process",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lp_agent_process") as batch_op:
        batch_op.create_index(
            "idx_lp_agent_process_document_id", ["document_id"], unique=False
        )
        batch_op.create_index("idx_lp_agent_process_status", ["status"], unique=False)

    # ── 9. New: lp_keywords ───────────────────────────────────────────────────
    op.create_table(
        "lp_keywords",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("lesson_id", sa.String(length=36), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lp_keywords") as batch_op:
        batch_op.create_index(
            "idx_lp_keywords_document_id", ["document_id"], unique=False
        )
        batch_op.create_index("idx_lp_keywords_lesson_id", ["lesson_id"], unique=False)

    # ── 10. New: lp_summaries ─────────────────────────────────────────────────
    op.create_table(
        "lp_summaries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("lesson_id", sa.String(length=36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lp_summaries") as batch_op:
        batch_op.create_index(
            "idx_lp_summaries_document_id", ["document_id"], unique=False
        )
        batch_op.create_index("idx_lp_summaries_lesson_id", ["lesson_id"], unique=False)

    # ── 11. New: lp_quiz_questions ────────────────────────────────────────────
    op.create_table(
        "lp_quiz_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("lesson_id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("choices", sa.Text(), nullable=False),  # JSON array
        sa.Column("correct_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lp_quiz_questions") as batch_op:
        batch_op.create_index(
            "idx_lp_quiz_questions_document_id", ["document_id"], unique=False
        )
        batch_op.create_index(
            "idx_lp_quiz_questions_lesson_id", ["lesson_id"], unique=False
        )

    # ── 12. New: lp_practice_questions ───────────────────────────────────────
    op.create_table(
        "lp_practice_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("lesson_id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("choices", sa.Text(), nullable=False),  # JSON array
        sa.Column("correct_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lp_practice_questions") as batch_op:
        batch_op.create_index(
            "idx_lp_practice_questions_document_id", ["document_id"], unique=False
        )
        batch_op.create_index(
            "idx_lp_practice_questions_lesson_id", ["lesson_id"], unique=False
        )

    # ── 13. New: lp_agent_flashcards ─────────────────────────────────────────
    op.create_table(
        "lp_agent_flashcards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("lesson_id", sa.String(length=36), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column(
            "source_type", sa.String(length=32), nullable=False, server_default="agent"
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lp_agent_flashcards") as batch_op:
        batch_op.create_index(
            "idx_lp_agent_flashcards_document_id", ["document_id"], unique=False
        )
        batch_op.create_index(
            "idx_lp_agent_flashcards_lesson_id", ["lesson_id"], unique=False
        )


def downgrade() -> None:
    # New tables
    op.drop_table("lp_agent_flashcards")
    op.drop_table("lp_practice_questions")
    op.drop_table("lp_quiz_questions")
    op.drop_table("lp_summaries")
    op.drop_table("lp_keywords")
    op.drop_table("lp_agent_process")

    # Restore renamed tables (reverse: lp_ → original names)
    # user_flashcards_request
    op.create_table(
        "user_flashcards_request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO user_flashcards_request SELECT * FROM lp_user_flashcards_request"
    )
    op.drop_table("lp_user_flashcards_request")

    # user_flashcards
    op.create_table(
        "user_flashcards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Uuid(), nullable=True),
        sa.Column("lesson_id", sa.Uuid(), nullable=True),
        sa.Column("is_generated", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO user_flashcards SELECT * FROM lp_user_flashcards")
    op.drop_table("lp_user_flashcards")

    # quizzes + user_quiz_progress
    op.create_table(
        "quizzes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO quizzes SELECT * FROM lp_quizzes")
    op.create_table(
        "user_quiz_progress",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "quiz_id"),
    )
    op.execute("INSERT INTO user_quiz_progress SELECT * FROM lp_user_quiz_progress")
    op.drop_table("lp_user_quiz_progress")
    op.drop_table("lp_quizzes")

    # practices + user_practice_progress
    op.create_table(
        "practices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("required_correct", sa.Integer(), nullable=False),
        sa.Column("total_questions", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("practice_type", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO practices SELECT * FROM lp_practices")
    op.create_table(
        "user_practice_progress",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("practice_id", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("best_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["practice_id"], ["practices.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "practice_id"),
    )
    op.execute(
        "INSERT INTO user_practice_progress SELECT * FROM lp_user_practice_progress"
    )
    op.drop_table("lp_user_practice_progress")
    op.drop_table("lp_practices")

    # flashcards
    op.create_table(
        "flashcards",
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("state", sa.Integer(), nullable=False),
        sa.Column("stability", sa.Float(), nullable=False),
        sa.Column("difficulty", sa.Float(), nullable=False),
        sa.Column("elapsed_days", sa.Integer(), nullable=False),
        sa.Column("scheduled_days", sa.Integer(), nullable=False),
        sa.Column("due", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("card_id"),
    )
    op.execute("INSERT INTO flashcards SELECT * FROM lp_flashcards")
    op.drop_table("lp_flashcards")
