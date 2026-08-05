"""add_lp_document_images

Revision ID: 8518cab04b91
Revises: 6352f7c6c312
Create Date: 2026-08-04 23:11:04.071834

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8518cab04b91"
down_revision: Union[str, Sequence[str], None] = "6352f7c6c312"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "lp_document_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("image_format", sa.String(16), nullable=False, server_default="PNG"),
        sa.Column("image_data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lp_document_images_document_id",
        "lp_document_images",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_lp_document_images_node_id",
        "lp_document_images",
        ["node_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_lp_document_images_node_id", table_name="lp_document_images")
    op.drop_index("ix_lp_document_images_document_id", table_name="lp_document_images")
    op.drop_table("lp_document_images")
