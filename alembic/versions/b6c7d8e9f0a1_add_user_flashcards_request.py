"""add user_flashcards_request table

Revision ID: b6c7d8e9f0a1
Revises: 8518cab04b91
Create Date: 2026-08-06 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, Sequence[str], None] = "8518cab04b91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_flashcards_request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'in_progress'"),
        ),
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
    op.create_index(
        "ix_user_flashcards_request_scope_target",
        "user_flashcards_request",
        ["scope", "target_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_flashcards_request_user_id",
        "user_flashcards_request",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_user_flashcards_request_active",
        "user_flashcards_request",
        ["scope", "target_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'in_progress')"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_user_flashcards_request_active",
        table_name="user_flashcards_request",
    )
    op.drop_index(
        "ix_user_flashcards_request_user_id",
        table_name="user_flashcards_request",
    )
    op.drop_index(
        "ix_user_flashcards_request_scope_target",
        table_name="user_flashcards_request",
    )
    op.drop_table("user_flashcards_request")
