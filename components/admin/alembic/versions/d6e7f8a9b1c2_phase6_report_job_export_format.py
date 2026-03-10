"""Add export format to admin report jobs

Revision ID: d6e7f8a9b1c2
Revises: c5d4e8a1b2f9
Create Date: 2026-03-29 23:40:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6e7f8a9b1c2"
down_revision: Union[str, Sequence[str], None] = "c5d4e8a1b2f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "admin_report_jobs",
        sa.Column("export_format", sa.String(length=10), nullable=True),
    )
    op.execute(
        "UPDATE admin_report_jobs SET export_format = 'json' WHERE export_format IS NULL"
    )
    op.alter_column("admin_report_jobs", "export_format", nullable=False)


def downgrade() -> None:
    op.drop_column("admin_report_jobs", "export_format")
