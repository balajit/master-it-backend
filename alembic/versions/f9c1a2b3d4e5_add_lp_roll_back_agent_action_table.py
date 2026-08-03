"""add lp rollback agent action table

Revision ID: f9c1a2b3d4e5
Revises: e2a4d6f8b9c1
Create Date: 2026-08-02 13:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f9c1a2b3d4e5"
down_revision: Union[str, Sequence[str], None] = "e2a4d6f8b9c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lp_roll_back_agent_action",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("target_key", sa.String(length=64), nullable=False),
        sa.Column("precheck_passed", sa.Boolean(), nullable=False),
        sa.Column("target_summary", sa.JSON(), nullable=True),
        sa.Column("undo_steps", sa.JSON(), nullable=True),
        sa.Column("integrity_hash", sa.String(length=64), nullable=False),
        sa.Column("affected_row_count", sa.Integer(), nullable=False),
        sa.Column("affected_file_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_lp_roll_back_agent_action_status",
        "lp_roll_back_agent_action",
        ["status"],
    )
    op.create_index(
        "idx_lp_roll_back_agent_action_created_at",
        "lp_roll_back_agent_action",
        ["created_at"],
    )
    op.create_index(
        "idx_lp_roll_back_agent_action_action_type",
        "lp_roll_back_agent_action",
        ["action_type"],
    )
    op.create_index(
        "uq_lp_roll_back_agent_action_prepared_target_key",
        "lp_roll_back_agent_action",
        ["target_key"],
        unique=True,
        postgresql_where=sa.text("status = 'prepared'"),
        sqlite_where=sa.text("status = 'prepared'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_lp_roll_back_agent_action_prepared_target_key",
        table_name="lp_roll_back_agent_action",
    )
    op.drop_index(
        "idx_lp_roll_back_agent_action_action_type",
        table_name="lp_roll_back_agent_action",
    )
    op.drop_index(
        "idx_lp_roll_back_agent_action_created_at",
        table_name="lp_roll_back_agent_action",
    )
    op.drop_index(
        "idx_lp_roll_back_agent_action_status",
        table_name="lp_roll_back_agent_action",
    )
    op.drop_table("lp_roll_back_agent_action")
