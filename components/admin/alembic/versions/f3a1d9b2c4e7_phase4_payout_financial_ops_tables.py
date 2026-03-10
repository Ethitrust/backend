"""Add phase 4 payout and financial operations tables

Revision ID: f3a1d9b2c4e7
Revises: e1f9b37c8a42
Create Date: 2026-03-30 09:15:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a1d9b2c4e7"
down_revision: Union[str, Sequence[str], None] = "e1f9b37c8a42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_payout_queue",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payout_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("wallet_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("provider_ref", sa.String(length=120), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_payout_queue_assignee_id"),
        "admin_payout_queue",
        ["assignee_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_payout_queue_currency"),
        "admin_payout_queue",
        ["currency"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_payout_queue_last_retry_at"),
        "admin_payout_queue",
        ["last_retry_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_payout_queue_payout_id"),
        "admin_payout_queue",
        ["payout_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_admin_payout_queue_priority"),
        "admin_payout_queue",
        ["priority"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_payout_queue_provider"),
        "admin_payout_queue",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_payout_queue_retry_count"),
        "admin_payout_queue",
        ["retry_count"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_payout_queue_status"),
        "admin_payout_queue",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_payout_queue_updated_at"),
        "admin_payout_queue",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_payout_queue_user_id"),
        "admin_payout_queue",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_payout_queue_wallet_id"),
        "admin_payout_queue",
        ["wallet_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admin_payout_queue_wallet_id"), table_name="admin_payout_queue"
    )
    op.drop_index(
        op.f("ix_admin_payout_queue_user_id"), table_name="admin_payout_queue"
    )
    op.drop_index(
        op.f("ix_admin_payout_queue_updated_at"), table_name="admin_payout_queue"
    )
    op.drop_index(op.f("ix_admin_payout_queue_status"), table_name="admin_payout_queue")
    op.drop_index(
        op.f("ix_admin_payout_queue_retry_count"), table_name="admin_payout_queue"
    )
    op.drop_index(
        op.f("ix_admin_payout_queue_provider"), table_name="admin_payout_queue"
    )
    op.drop_index(
        op.f("ix_admin_payout_queue_priority"), table_name="admin_payout_queue"
    )
    op.drop_index(
        op.f("ix_admin_payout_queue_payout_id"), table_name="admin_payout_queue"
    )
    op.drop_index(
        op.f("ix_admin_payout_queue_last_retry_at"), table_name="admin_payout_queue"
    )
    op.drop_index(
        op.f("ix_admin_payout_queue_currency"), table_name="admin_payout_queue"
    )
    op.drop_index(
        op.f("ix_admin_payout_queue_assignee_id"), table_name="admin_payout_queue"
    )
    op.drop_table("admin_payout_queue")
