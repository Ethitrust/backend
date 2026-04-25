"""dispute chat and mediation flow

Revision ID: c3d9b2f1a410
Revises: e571567d8522
Create Date: 2026-04-25 10:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d9b2f1a410"
down_revision: Union[str, Sequence[str], None] = "e571567d8522"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("disputes", "status", type_=sa.String(length=40), existing_type=sa.String(length=30))

    op.add_column("disputes", sa.Column("negotiation_started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.add_column("disputes", sa.Column("negotiation_deadline_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now() + interval '48 hours'")))
    op.add_column("disputes", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("disputes", sa.Column("assigned_mediator_id", sa.UUID(), nullable=True))
    op.add_column("disputes", sa.Column("settlement_requested_by", sa.UUID(), nullable=True))
    op.add_column("disputes", sa.Column("settlement_confirmed_by", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_disputes_negotiation_deadline_at"), "disputes", ["negotiation_deadline_at"], unique=False)

    op.add_column("dispute_evidence", sa.Column("object_key", sa.String(length=512), nullable=True))
    op.add_column("dispute_evidence", sa.Column("message_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_dispute_evidence_message_id"), "dispute_evidence", ["message_id"], unique=False)

    op.create_table(
        "dispute_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dispute_id", sa.UUID(), nullable=False),
        sa.Column("sender_id", sa.UUID(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dispute_messages_dispute_id"), "dispute_messages", ["dispute_id"], unique=False)
    op.create_index(op.f("ix_dispute_messages_created_at"), "dispute_messages", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dispute_messages_created_at"), table_name="dispute_messages")
    op.drop_index(op.f("ix_dispute_messages_dispute_id"), table_name="dispute_messages")
    op.drop_table("dispute_messages")

    op.drop_index(op.f("ix_dispute_evidence_message_id"), table_name="dispute_evidence")
    op.drop_column("dispute_evidence", "message_id")
    op.drop_column("dispute_evidence", "object_key")

    op.drop_index(op.f("ix_disputes_negotiation_deadline_at"), table_name="disputes")
    op.drop_column("disputes", "settlement_confirmed_by")
    op.drop_column("disputes", "settlement_requested_by")
    op.drop_column("disputes", "assigned_mediator_id")
    op.drop_column("disputes", "escalated_at")
    op.drop_column("disputes", "negotiation_deadline_at")
    op.drop_column("disputes", "negotiation_started_at")

    op.alter_column("disputes", "status", type_=sa.String(length=30), existing_type=sa.String(length=40))
