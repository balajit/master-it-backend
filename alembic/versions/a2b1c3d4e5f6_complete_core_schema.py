"""Complete core schema — tables/columns that previously relied on create_all.

Revision ID: a2b1c3d4e5f6
Revises: 9f4a2c1d8b7e
Create Date: 2026-07-29

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2b1c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9f4a2c1d8b7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def _fk_exists(table: str, columns: list[str], ref_table: str) -> bool:
    if not _table_exists(table):
        return False
    bind = op.get_bind()
    target = tuple(columns)
    for fk in sa.inspect(bind).get_foreign_keys(table):
        if (
            tuple(fk.get("constrained_columns") or []) == target
            and fk.get("referred_table") == ref_table
        ):
            return True
    return False


def _index_exists(table: str, index_name: str) -> bool:
    if not _table_exists(table):
        return False
    bind = op.get_bind()
    return any(i["name"] == index_name for i in sa.inspect(bind).get_indexes(table))


# ── users ────────────────────────────────────────────────────────────────────

_USERS_COLUMNS: list[tuple[str, sa.TypeEngine, bool, str | None]] = [
    ("google_id", sa.String(), True, None),
    ("email", sa.String(), False, None),
    ("name", sa.String(), False, ""),
    ("picture_url", sa.String(), False, ""),
    ("password_hash", sa.String(), True, None),
    ("phone", sa.String(), True, None),
]


def _add_users_missing_columns() -> None:
    for col_name, col_type, nullable, default in _USERS_COLUMNS:
        if not _column_exists("users", col_name):
            op.add_column(
                "users",
                sa.Column(
                    col_name, col_type, nullable=nullable, server_default=default
                ),
            )


def _ensure_users_constraints() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraints = [
        uc.get("column_names") for uc in inspector.get_unique_constraints("users")
    ]
    col_names = [c["name"] for c in inspector.get_columns("users")]
    if "google_id" in col_names and not any(
        ["google_id" in (c or []) for c in constraints]
    ):
        op.create_unique_constraint("uq_users_google_id", "users", ["google_id"])
    if "email" in col_names and not any(["email" in (c or []) for c in constraints]):
        op.create_unique_constraint("uq_users_email", "users", ["email"])


# ── courses ──────────────────────────────────────────────────────────────────

_COURSES_COLUMNS: list[tuple[str, sa.TypeEngine, bool, str | None]] = [
    ("title", sa.String(), False, None),
    ("description", sa.String(), False, ""),
    ("number_of_credits", sa.Integer(), False, "0"),
    ("difficulty", sa.String(), False, "beginner"),
    ("status", sa.String(), False, "COMING_SOON"),
    ("owner_id", sa.Integer(), False, None),
    ("created_at", sa.String(), False, ""),
    ("updated_at", sa.String(), False, ""),
]


def _add_courses_missing_columns() -> None:
    for col_name, col_type, nullable, default in _COURSES_COLUMNS:
        if not _column_exists("courses", col_name):
            kwargs: dict = {"nullable": nullable}
            if default is not None:
                kwargs["server_default"] = default
            # owner_id needs a FK so add it without FK for now
            op.add_column("courses", sa.Column(col_name, col_type, **kwargs))


def _ensure_courses_constraints() -> None:
    if not _fk_exists("courses", ["owner_id"], "users") and _column_exists(
        "courses", "owner_id"
    ):
        op.create_foreign_key(
            "fk_courses_owner_id_users", "courses", "users", ["owner_id"], ["id"]
        )
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    col_names = [c["name"] for c in inspector.get_columns("courses")]
    constraints = [
        uc.get("column_names") for uc in inspector.get_unique_constraints("courses")
    ]
    if "title" in col_names and not any(["title" in (c or []) for c in constraints]):
        op.create_unique_constraint("uq_courses_title", "courses", ["title"])


# ── Missing FK constraints on learning-domain tables ────────────────────────

_LEARNING_FKS: list[tuple[str, list[str], str]] = [
    ("units", ["course_id"], "courses"),
    ("sections", ["unit_id"], "units"),
    ("lessons", ["section_id"], "sections"),
    ("practices", ["section_id"], "sections"),
    ("quizzes", ["section_id"], "sections"),
]


def _add_missing_learning_fks() -> None:
    for table, columns, ref_table in _LEARNING_FKS:
        if (
            not _fk_exists(table, columns, ref_table)
            and _table_exists(table)
            and _table_exists(ref_table)
        ):
            fk_name = f"fk_{table}_{columns[0]}_{ref_table}"
            op.create_foreign_key(fk_name, table, ref_table, columns, ["id"])


# ── Tables with zero migration coverage ─────────────────────────────────────


def _create_if_missing(table_name: str, *columns: sa.Column) -> None:
    if _table_exists(table_name):
        return
    op.create_table(table_name, *columns)


def _ensure_sessions() -> None:
    if _table_exists("sessions"):
        return
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def _ensure_roles() -> None:
    if _table_exists("roles"):
        return
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def _ensure_user_roles() -> None:
    if _table_exists("user_roles"):
        return
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), primary_key=True),
    )


def _ensure_permissions() -> None:
    if _table_exists("permissions"):
        return
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )


def _ensure_role_permissions() -> None:
    if _table_exists("role_permissions"):
        return
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), primary_key=True),
        sa.Column(
            "permission_id",
            sa.Integer(),
            sa.ForeignKey("permissions.id"),
            primary_key=True,
        ),
    )


def _ensure_documents() -> None:
    if _table_exists("documents"):
        return
    op.create_table(
        "documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def _ensure_course_documents() -> None:
    if _table_exists("course_documents"):
        return
    op.create_table(
        "course_documents",
        sa.Column(
            "course_id", sa.Integer(), sa.ForeignKey("courses.id"), primary_key=True
        ),
        sa.Column(
            "document_id", sa.String(), sa.ForeignKey("documents.id"), primary_key=True
        ),
    )


def _ensure_course_templates() -> None:
    if _table_exists("course_templates"):
        return
    op.create_table(
        "course_templates",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column(
            "file_id", sa.String(), sa.ForeignKey("documents.id"), nullable=False
        ),
        sa.Column("structure", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("course_id"),
    )


def _ensure_student_progress() -> None:
    if _table_exists("student_progress"):
        return
    op.create_table(
        "student_progress",
        sa.Column(
            "student_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column("node_id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False, server_default="LOCKED"),
        sa.Column("continuous_score", sa.Float(), nullable=False, server_default="0.0"),
    )


def _ensure_flashcards() -> None:
    if _table_exists("flashcards"):
        return
    op.create_table(
        "flashcards",
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column(
            "student_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("state", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stability", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("difficulty", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("elapsed_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("due", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("card_id"),
    )


def _ensure_user_notes() -> None:
    if _table_exists("user_notes"):
        return
    op.create_table(
        "user_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=True),
        sa.Column(
            "lesson_id", sa.Integer(), sa.ForeignKey("lessons.id"), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("user_notes", "idx_user_notes_user_id"):
        op.create_index("idx_user_notes_user_id", "user_notes", ["user_id"])
    if not _index_exists("user_notes", "idx_user_notes_unit_id"):
        op.create_index("idx_user_notes_unit_id", "user_notes", ["unit_id"])
    if not _index_exists("user_notes", "idx_user_notes_lesson_id"):
        op.create_index("idx_user_notes_lesson_id", "user_notes", ["lesson_id"])


def _ensure_user_flashcards() -> None:
    if _table_exists("user_flashcards"):
        return
    op.create_table(
        "user_flashcards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column(
            "course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=True
        ),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=True),
        sa.Column(
            "lesson_id", sa.Integer(), sa.ForeignKey("lessons.id"), nullable=True
        ),
        sa.Column("is_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    for idx_name, col in [
        ("idx_user_flashcards_user_id", "user_id"),
        ("idx_user_flashcards_created_by", "created_by"),
        ("idx_user_flashcards_course_id", "course_id"),
        ("idx_user_flashcards_unit_id", "unit_id"),
        ("idx_user_flashcards_lesson_id", "lesson_id"),
    ]:
        if not _index_exists("user_flashcards", idx_name):
            op.create_index(idx_name, "user_flashcards", [col])


def upgrade() -> None:
    # Add columns to minimally-bootstrapped tables
    _add_users_missing_columns()
    _add_courses_missing_columns()

    # Add constraints
    _ensure_users_constraints()
    _ensure_courses_constraints()

    # Add missing FK constraints on learning-domain tables
    _add_missing_learning_fks()

    # Create tables that have zero migration coverage
    _ensure_sessions()
    _ensure_roles()
    _ensure_user_roles()
    _ensure_permissions()
    _ensure_role_permissions()
    _ensure_documents()
    _ensure_course_documents()
    _ensure_course_templates()
    _ensure_student_progress()
    _ensure_flashcards()
    _ensure_user_notes()
    _ensure_user_flashcards()


def downgrade() -> None:
    # NOTE: downgrade is intentionally a no-op. These tables existed before this
    # migration (via create_all), so dropping them would break existing data.
    # A production downgrade should be planned with data-migration awareness.
    pass
