"""add active unique index on lp_document_process abs_path

Revision ID: c4d5e6f7a8b9
Revises: f1a2b3c4d5e6
Create Date: 2026-07-29 23:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    if _index_exists("lp_document_process", "uq_lp_document_process_active_abs_path"):
        return
    op.create_index(
        "uq_lp_document_process_active_abs_path",
        "lp_document_process",
        ["abs_path"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending','processing')"),
        sqlite_where=sa.text("status IN ('pending','processing')"),
    )


def downgrade() -> None:
    if not _index_exists(
        "lp_document_process", "uq_lp_document_process_active_abs_path"
    ):
        return
    op.drop_index(
        "uq_lp_document_process_active_abs_path",
        table_name="lp_document_process",
    )
