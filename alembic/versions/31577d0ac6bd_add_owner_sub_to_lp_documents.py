"""add_owner_sub_to_lp_documents

Revision ID: 31577d0ac6bd
Revises: 5f69250fbce0
Create Date: 2026-07-28 15:33:28.683262

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "31577d0ac6bd"
down_revision: Union[str, Sequence[str], None] = "5f69250fbce0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "lp_documents",
        sa.Column("owner_sub", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_lp_documents_owner_sub",
        "lp_documents",
        ["owner_sub"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_lp_documents_owner_sub", table_name="lp_documents")
    op.drop_column("lp_documents", "owner_sub")
