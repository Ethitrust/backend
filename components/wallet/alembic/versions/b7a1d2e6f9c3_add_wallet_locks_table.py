"""add wallet locks table

Revision ID: b7a1d2e6f9c3
Revises: adc6396c6c4d
Create Date: 2026-03-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7a1d2e6f9c3"
down_revision: Union[str, Sequence[str], None] = "adc6396c6c4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "wallet_locks",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="locked"
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.CheckConstraint("amount > 0", name="ck_wallet_lock_amount_positive"),
        sa.CheckConstraint(
            "status IN ('locked', 'released', 'captured', 'cancelled')",
            name="ck_wallet_lock_status_valid",
        ),
        sa.UniqueConstraint("reference", name="uq_wallet_lock_reference"),
    )

    op.create_index("ix_wallet_locks_wallet_id", "wallet_locks", ["wallet_id"])
    op.create_index("ix_wallet_locks_source_id", "wallet_locks", ["source_id"])
    op.create_index("ix_wallet_locks_status", "wallet_locks", ["status"])
    op.create_index(
        "ix_wallet_locks_source_type_source_id",
        "wallet_locks",
        ["source_type", "source_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_wallet_locks_source_type_source_id", table_name="wallet_locks")
    op.drop_index("ix_wallet_locks_status", table_name="wallet_locks")
    op.drop_index("ix_wallet_locks_source_id", table_name="wallet_locks")
    op.drop_index("ix_wallet_locks_wallet_id", table_name="wallet_locks")
    op.drop_table("wallet_locks")
