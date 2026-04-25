"""add submitted/in_review escrow statuses

Revision ID: f3c7b4d95e21
Revises: 96aa146995e1
Create Date: 2026-04-23 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c7b4d95e21"
down_revision: Union[str, Sequence[str], None] = "96aa146995e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("ck_escrows_status", "escrows", type_="check")
    op.create_check_constraint(
        "ck_escrows_status",
        "escrows",
        "status IN ('invited', 'counter_pending_initiator', 'counter_pending_counterparty', 'rejected', 'expired', 'pending', 'active', 'submitted', 'in_review', 'completed', 'disputed', 'cancelled', 'refunded')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_escrows_status", "escrows", type_="check")
    op.create_check_constraint(
        "ck_escrows_status",
        "escrows",
        "status IN ('invited', 'counter_pending_initiator', 'counter_pending_counterparty', 'rejected', 'expired', 'pending', 'active', 'completed', 'disputed', 'cancelled', 'refunded')",
    )
