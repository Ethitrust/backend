"""Add phase 3 dispute command-center tables

Revision ID: e1f9b37c8a42
Revises: a94f2d8c1b7e
Create Date: 2026-03-29 20:45:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f9b37c8a42"
down_revision: Union[str, Sequence[str], None] = "a94f2d8c1b7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_dispute_queue",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dispute_id", sa.UUID(), nullable=False),
        sa.Column("escrow_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("raised_by", sa.UUID(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
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
        op.f("ix_admin_dispute_queue_assignee_id"),
        "admin_dispute_queue",
        ["assignee_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_queue_dispute_id"),
        "admin_dispute_queue",
        ["dispute_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_admin_dispute_queue_escrow_id"),
        "admin_dispute_queue",
        ["escrow_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_queue_priority"),
        "admin_dispute_queue",
        ["priority"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_queue_raised_by"),
        "admin_dispute_queue",
        ["raised_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_queue_status"),
        "admin_dispute_queue",
        ["status"],
        unique=False,
    )

    op.create_table(
        "admin_dispute_evidence_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dispute_id", sa.UUID(), nullable=False),
        sa.Column("requested_from_user_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_dispute_evidence_requests_dispute_id"),
        "admin_dispute_evidence_requests",
        ["dispute_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_evidence_requests_requested_by"),
        "admin_dispute_evidence_requests",
        ["requested_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_evidence_requests_requested_from_user_id"),
        "admin_dispute_evidence_requests",
        ["requested_from_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_evidence_requests_status"),
        "admin_dispute_evidence_requests",
        ["status"],
        unique=False,
    )

    op.create_table(
        "admin_dispute_internal_notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dispute_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_dispute_internal_notes_author_id"),
        "admin_dispute_internal_notes",
        ["author_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_internal_notes_dispute_id"),
        "admin_dispute_internal_notes",
        ["dispute_id"],
        unique=False,
    )

    op.create_table(
        "admin_dispute_resolution_rationales",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dispute_id", sa.UUID(), nullable=False),
        sa.Column("escrow_id", sa.UUID(), nullable=False),
        sa.Column("resolution", sa.String(length=20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("apply_fee_refund", sa.Boolean(), nullable=False),
        sa.Column("fee_refund_status", sa.String(length=30), nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_dispute_resolution_rationales_decided_by"),
        "admin_dispute_resolution_rationales",
        ["decided_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_resolution_rationales_dispute_id"),
        "admin_dispute_resolution_rationales",
        ["dispute_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_resolution_rationales_escrow_id"),
        "admin_dispute_resolution_rationales",
        ["escrow_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_dispute_resolution_rationales_resolution"),
        "admin_dispute_resolution_rationales",
        ["resolution"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admin_dispute_resolution_rationales_resolution"),
        table_name="admin_dispute_resolution_rationales",
    )
    op.drop_index(
        op.f("ix_admin_dispute_resolution_rationales_escrow_id"),
        table_name="admin_dispute_resolution_rationales",
    )
    op.drop_index(
        op.f("ix_admin_dispute_resolution_rationales_dispute_id"),
        table_name="admin_dispute_resolution_rationales",
    )
    op.drop_index(
        op.f("ix_admin_dispute_resolution_rationales_decided_by"),
        table_name="admin_dispute_resolution_rationales",
    )
    op.drop_table("admin_dispute_resolution_rationales")

    op.drop_index(
        op.f("ix_admin_dispute_internal_notes_dispute_id"),
        table_name="admin_dispute_internal_notes",
    )
    op.drop_index(
        op.f("ix_admin_dispute_internal_notes_author_id"),
        table_name="admin_dispute_internal_notes",
    )
    op.drop_table("admin_dispute_internal_notes")

    op.drop_index(
        op.f("ix_admin_dispute_evidence_requests_status"),
        table_name="admin_dispute_evidence_requests",
    )
    op.drop_index(
        op.f("ix_admin_dispute_evidence_requests_requested_from_user_id"),
        table_name="admin_dispute_evidence_requests",
    )
    op.drop_index(
        op.f("ix_admin_dispute_evidence_requests_requested_by"),
        table_name="admin_dispute_evidence_requests",
    )
    op.drop_index(
        op.f("ix_admin_dispute_evidence_requests_dispute_id"),
        table_name="admin_dispute_evidence_requests",
    )
    op.drop_table("admin_dispute_evidence_requests")

    op.drop_index(
        op.f("ix_admin_dispute_queue_status"), table_name="admin_dispute_queue"
    )
    op.drop_index(
        op.f("ix_admin_dispute_queue_raised_by"), table_name="admin_dispute_queue"
    )
    op.drop_index(
        op.f("ix_admin_dispute_queue_priority"), table_name="admin_dispute_queue"
    )
    op.drop_index(
        op.f("ix_admin_dispute_queue_escrow_id"), table_name="admin_dispute_queue"
    )
    op.drop_index(
        op.f("ix_admin_dispute_queue_dispute_id"), table_name="admin_dispute_queue"
    )
    op.drop_index(
        op.f("ix_admin_dispute_queue_assignee_id"), table_name="admin_dispute_queue"
    )
    op.drop_table("admin_dispute_queue")
