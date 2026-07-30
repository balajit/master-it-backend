"""add resume state fields to lp_document_process

Revision ID: d1e2f3a4b5c6
Revises: c4d5e6f7a8b9
Create Date: 2026-07-30 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lp_document_process",
        sa.Column(
            "run_mode",
            sa.String(length=16),
            nullable=False,
            server_default="process",
        ),
    )
    op.add_column(
        "lp_document_process",
        sa.Column(
            "last_completed_stage",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "lp_document_process",
        sa.Column(
            "failed_stage",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "lp_document_process",
        sa.Column(
            "resume_state",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("lp_document_process", "resume_state")
    op.drop_column("lp_document_process", "failed_stage")
    op.drop_column("lp_document_process", "last_completed_stage")
    op.drop_column("lp_document_process", "run_mode")
