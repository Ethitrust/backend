"""Initial tables

Revision ID: cc2605150e48
Revises: 8688e47af205
Create Date: 2026-03-21 19:26:07.253038

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cc2605150e48'
down_revision: Union[str, Sequence[str], None] = '8688e47af205'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
