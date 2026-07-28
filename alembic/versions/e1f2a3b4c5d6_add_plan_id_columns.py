"""Add plan_lesson_id cross-reference column to lessons.

Stores the LP LearningUnit UUID (StudyPlan.Lesson.unit_id == BookLesson.unit_id)
so the study-plan API can join from a CanonicalBook lesson back to the
master-it LessonModel integer PK, enabling the frontend to call
progress/notes/flashcard APIs with integer IDs.

Revision ID: e1f2a3b4c5d6
Revises: c9e2f4a1b7d3
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "c9e2f4a1b7d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column("plan_lesson_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("lessons") as batch_op:
        batch_op.drop_column("plan_lesson_id")
