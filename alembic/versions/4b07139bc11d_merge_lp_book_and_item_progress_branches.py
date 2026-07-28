"""merge_lp_book_and_item_progress_branches

Revision ID: 4b07139bc11d
Revises: a7f3c1b8e2d9, e1f2a3b4c5d6
Create Date: 2026-07-28 12:26:08.786490

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b07139bc11d'
down_revision: Union[str, Sequence[str], None] = ('a7f3c1b8e2d9', 'e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
