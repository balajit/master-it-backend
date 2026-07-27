"""study screen columns: unit.about, practices.practice_type, user_lesson_progress.last_accessed_at

Revision ID: a1b2c3d4e5f6
Revises: 38ce77c986ab
Create Date: 2026-07-26 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "38ce77c986ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "units", sa.Column("about", sa.Text(), nullable=True, server_default="")
    )
    op.add_column(
        "practices",
        sa.Column(
            "practice_type", sa.String(), nullable=True, server_default="practice"
        ),
    )
    op.add_column(
        "user_lesson_progress",
        sa.Column("last_accessed_at", sa.String(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("user_lesson_progress") as batch_op:
        batch_op.drop_column("last_accessed_at")
    with op.batch_alter_table("practices") as batch_op:
        batch_op.drop_column("practice_type")
    with op.batch_alter_table("units") as batch_op:
        batch_op.drop_column("about")
