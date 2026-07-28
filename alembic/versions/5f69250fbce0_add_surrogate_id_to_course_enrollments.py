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
    # 1. Drop the FK from item_progress that references course_enrollments.user_id
    with op.batch_alter_table("item_progress", schema=None) as batch_op:
        batch_op.drop_constraint("item_progress_enrollment_id_fkey", type_="foreignkey")

    # 2. Drop the composite PK on course_enrollments
    with op.batch_alter_table("course_enrollments", schema=None) as batch_op:
        batch_op.drop_constraint("course_enrollments_pkey", type_="primary")

    # 3. Add surrogate id column
    op.add_column(
        "course_enrollments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    )

    # 4. Populate id for existing rows (uses a sequence-backed expression)
    op.execute(
        """
        WITH numbered AS (
            SELECT ctid, row_number() OVER () AS rn
            FROM course_enrollments
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

    # 6. Add PK on id
    with op.batch_alter_table("course_enrollments", schema=None) as batch_op:
        batch_op.create_primary_key("course_enrollments_pkey", ["id"])
        batch_op.create_unique_constraint(
            "uq_enrollment_user_course", ["user_id", "course_id"]
        )

    # 7. Restore FK on item_progress pointing to the new id column
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
