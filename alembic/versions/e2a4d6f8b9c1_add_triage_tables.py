"""add triage run and finding tables

Revision ID: e2a4d6f8b9c1
Revises: d1e2f3a4b5c6
Create Date: 2026-08-02 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e2a4d6f8b9c1"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "triage_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope_kind", sa.String(length=32), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=True),
        sa.Column("report_id", sa.String(length=128), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_triage_runs_created_at", "triage_runs", ["created_at"])
    op.create_index("idx_triage_runs_scope", "triage_runs", ["scope_kind"])
    op.create_index("idx_triage_runs_status", "triage_runs", ["status"])

    op.create_table(
        "triage_findings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("affected_count", sa.Integer(), nullable=False),
        sa.Column("sample_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["triage_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_triage_findings_run_id", "triage_findings", ["run_id"])
    op.create_index("idx_triage_findings_table", "triage_findings", ["table_name"])
    op.create_index("idx_triage_findings_severity", "triage_findings", ["severity"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_triage_findings_severity", table_name="triage_findings")
    op.drop_index("idx_triage_findings_table", table_name="triage_findings")
    op.drop_index("idx_triage_findings_run_id", table_name="triage_findings")
    op.drop_table("triage_findings")

    op.drop_index("idx_triage_runs_status", table_name="triage_runs")
    op.drop_index("idx_triage_runs_scope", table_name="triage_runs")
    op.drop_index("idx_triage_runs_created_at", table_name="triage_runs")
    op.drop_table("triage_runs")
