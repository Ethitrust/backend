"""Initial tables

Revision ID: adc6396c6c4d
Revises:
Create Date: 2026-03-21 19:31:25.029110

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "adc6396c6c4d"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("wallets"):
        op.create_table(
            "wallets",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("currency", sa.String(length=10), nullable=False),
            sa.Column("balance", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column(
                "locked_balance", sa.BigInteger(), nullable=False, server_default="0"
            ),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default="active"
            ),
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
                nullable=False,
            ),
            sa.CheckConstraint("balance >= 0", name="ck_wallet_balance_non_negative"),
            sa.CheckConstraint(
                "locked_balance >= 0", name="ck_wallet_locked_balance_non_negative"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "owner_id", "currency", name="uq_wallet_owner_currency"
            ),
        )

    wallet_indexes = {idx["name"] for idx in inspector.get_indexes("wallets")}
    if "ix_wallets_owner_id" not in wallet_indexes:
        op.create_index("ix_wallets_owner_id", "wallets", ["owner_id"])

    if not inspector.has_table("transactions"):
        op.create_table(
            "transactions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("escrow_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("type", sa.String(length=30), nullable=False),
            sa.Column("amount", sa.BigInteger(), nullable=False),
            sa.Column("currency", sa.String(length=10), nullable=False),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default="pending"
            ),
            sa.Column("reference", sa.String(length=255), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("reference"),
        )

    tx_indexes = {idx["name"] for idx in inspector.get_indexes("transactions")}
    if "ix_transactions_wallet_id" not in tx_indexes:
        op.create_index("ix_transactions_wallet_id", "transactions", ["wallet_id"])


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("transactions"):
        tx_indexes = {idx["name"] for idx in inspector.get_indexes("transactions")}
        if "ix_transactions_wallet_id" in tx_indexes:
            op.drop_index("ix_transactions_wallet_id", table_name="transactions")
        op.drop_table("transactions")

    if inspector.has_table("wallets"):
        wallet_indexes = {idx["name"] for idx in inspector.get_indexes("wallets")}
        if "ix_wallets_owner_id" in wallet_indexes:
            op.drop_index("ix_wallets_owner_id", table_name="wallets")
        op.drop_table("wallets")
