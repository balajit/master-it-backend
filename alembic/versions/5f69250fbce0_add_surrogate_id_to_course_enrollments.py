"""add_surrogate_id_to_course_enrollments

Adds a surrogate integer PK to course_enrollments and demotes (user_id, course_id)
to a unique constraint. Updates item_progress.enrollment_id FK to reference the new
surrogate id column instead of user_id.

Revision ID: 5f69250fbce0
Revises: 4b07139bc11d
Create Date: 2026-07-28 12:26:18.233736

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "5f69250fbce0"
down_revision: Union[str, Sequence[str], None] = "4b07139bc11d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add surrogate id PK to course_enrollments; fix item_progress FK."""
    bind = op.get_bind()

    def _column_exists(table: str, column: str) -> bool:
        return any(c["name"] == column for c in sa.inspect(bind).get_columns(table))

    def _fk_exists(table: str, name: str) -> bool:
        return any(
            fk.get("name") == name for fk in sa.inspect(bind).get_foreign_keys(table)
        )

    def _pk_name(table: str) -> str | None:
        return sa.inspect(bind).get_pk_constraint(table).get("name")

    def _pk_columns(table: str) -> list[str]:
        return list(
            sa.inspect(bind).get_pk_constraint(table).get("constrained_columns") or []
        )

    def _unique_exists(table: str, name: str) -> bool:
        return any(
            uc.get("name") == name
            for uc in sa.inspect(bind).get_unique_constraints(table)
        )

    # 1. Drop the FK from item_progress that references course_enrollments.user_id
    if _fk_exists("item_progress", "item_progress_enrollment_id_fkey"):
        with op.batch_alter_table("item_progress", schema=None) as batch_op:
            batch_op.drop_constraint(
                "item_progress_enrollment_id_fkey", type_="foreignkey"
            )

    # 2. Drop the composite PK on course_enrollments
    current_pk_name = _pk_name("course_enrollments")
    current_pk_columns = _pk_columns("course_enrollments")
    if current_pk_columns != ["id"] and current_pk_name is not None:
        with op.batch_alter_table("course_enrollments", schema=None) as batch_op:
            batch_op.drop_constraint(current_pk_name, type_="primary")

    # 3. Add surrogate id column
    if not _column_exists("course_enrollments", "id"):
        op.add_column(
            "course_enrollments",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=True),
        )

    # 4. Populate id for rows where it is still NULL
    if _column_exists("course_enrollments", "id"):
        op.execute(
            """
            WITH numbered AS (
                SELECT ctid, row_number() OVER () AS rn
                FROM course_enrollments
                WHERE id IS NULL
            )
            UPDATE course_enrollments ce
            SET id = n.rn
            FROM numbered n
            WHERE ce.ctid = n.ctid
            """
        )

    # 5. Create the sequence and tie it to the column
    op.execute("CREATE SEQUENCE IF NOT EXISTS course_enrollments_id_seq")
    op.execute(
        "SELECT setval('course_enrollments_id_seq', COALESCE((SELECT MAX(id) FROM course_enrollments), 0) + 1, false)"
    )
    op.execute(
        "ALTER TABLE course_enrollments ALTER COLUMN id SET DEFAULT nextval('course_enrollments_id_seq')"
    )
    op.execute(
        "ALTER SEQUENCE course_enrollments_id_seq OWNED BY course_enrollments.id"
    )
    op.execute("ALTER TABLE course_enrollments ALTER COLUMN id SET NOT NULL")

    # 6. Add PK on id
    if _pk_columns("course_enrollments") != ["id"]:
        with op.batch_alter_table("course_enrollments", schema=None) as batch_op:
            batch_op.create_primary_key("course_enrollments_pkey", ["id"])

    if not _unique_exists("course_enrollments", "uq_enrollment_user_course"):
        with op.batch_alter_table("course_enrollments", schema=None) as batch_op:
            batch_op.create_unique_constraint(
                "uq_enrollment_user_course", ["user_id", "course_id"]
            )

    # 7. Restore FK on item_progress pointing to the new id column
    if not _fk_exists("item_progress", "item_progress_enrollment_id_fkey"):
        with op.batch_alter_table("item_progress", schema=None) as batch_op:
            batch_op.create_foreign_key(
                "item_progress_enrollment_id_fkey",
                "course_enrollments",
                ["enrollment_id"],
                ["id"],
            )


def downgrade() -> None:
    """Revert course_enrollments to composite PK; restore old FK on item_progress."""
    # 1. Drop FK from item_progress
    with op.batch_alter_table("item_progress", schema=None) as batch_op:
        batch_op.drop_constraint("item_progress_enrollment_id_fkey", type_="foreignkey")

    # 2. Drop unique constraint and PK on course_enrollments
    with op.batch_alter_table("course_enrollments", schema=None) as batch_op:
        batch_op.drop_constraint("uq_enrollment_user_course", type_="unique")
        batch_op.drop_constraint("course_enrollments_pkey", type_="primary")

    # 3. Remove surrogate id column
    op.drop_column("course_enrollments", "id")
    op.execute("DROP SEQUENCE IF EXISTS course_enrollments_id_seq")

    # 4. Restore composite PK
    with op.batch_alter_table("course_enrollments", schema=None) as batch_op:
        batch_op.create_primary_key("course_enrollments_pkey", ["user_id", "course_id"])

    # 5. Restore old (incorrect) FK — references user_id to match pre-migration state
    with op.batch_alter_table("item_progress", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "item_progress_enrollment_id_fkey",
            "course_enrollments",
            ["enrollment_id"],
            ["user_id"],
        )
