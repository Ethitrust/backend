"""add tamper fields to evidence

Revision ID: f681567d8523
Revises: e571567d8522
Create Date: 2026-04-25 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f681567d8523'
down_revision: Union[str, Sequence[str], None] = 'e571567d8522'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dispute_evidence', sa.Column('is_tampered', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('dispute_evidence', sa.Column('tamper_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('dispute_evidence', 'tamper_metadata')
    op.drop_column('dispute_evidence', 'is_tampered')
