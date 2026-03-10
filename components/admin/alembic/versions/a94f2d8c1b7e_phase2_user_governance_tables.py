"""Add phase 2 user governance tables

Revision ID: a94f2d8c1b7e
Revises: 7c4a6b4f3d1e
Create Date: 2026-03-29 19:20:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a94f2d8c1b7e"
down_revision: Union[str, Sequence[str], None] = "7c4a6b4f3d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_verification_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("overridden_by", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("review_case_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id"], ["admin_review_cases.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_verification_overrides_idempotency_key"),
        "admin_verification_overrides",
        ["idempotency_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_verification_overrides_overridden_by"),
        "admin_verification_overrides",
        ["overridden_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_verification_overrides_review_case_id"),
        "admin_verification_overrides",
        ["review_case_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_verification_overrides_user_id"),
        "admin_verification_overrides",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "admin_risk_flags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("flag", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_risk_flags_created_by"),
        "admin_risk_flags",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_risk_flags_flag"),
        "admin_risk_flags",
        ["flag"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_risk_flags_severity"),
        "admin_risk_flags",
        ["severity"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_risk_flags_status"),
        "admin_risk_flags",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_risk_flags_user_id"),
        "admin_risk_flags",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "admin_idempotency_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "action",
            "idempotency_key",
            name="uq_admin_idempotency_action_key",
        ),
    )
    op.create_index(
        op.f("ix_admin_idempotency_keys_action"),
        "admin_idempotency_keys",
        ["action"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_idempotency_keys_actor_id"),
        "admin_idempotency_keys",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_idempotency_keys_idempotency_key"),
        "admin_idempotency_keys",
        ["idempotency_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admin_idempotency_keys_idempotency_key"),
        table_name="admin_idempotency_keys",
    )
    op.drop_index(
        op.f("ix_admin_idempotency_keys_actor_id"),
        table_name="admin_idempotency_keys",
    )
    op.drop_index(
        op.f("ix_admin_idempotency_keys_action"),
        table_name="admin_idempotency_keys",
    )
    op.drop_table("admin_idempotency_keys")

    op.drop_index(op.f("ix_admin_risk_flags_user_id"), table_name="admin_risk_flags")
    op.drop_index(op.f("ix_admin_risk_flags_status"), table_name="admin_risk_flags")
    op.drop_index(
        op.f("ix_admin_risk_flags_severity"),
        table_name="admin_risk_flags",
    )
    op.drop_index(op.f("ix_admin_risk_flags_flag"), table_name="admin_risk_flags")
    op.drop_index(
        op.f("ix_admin_risk_flags_created_by"),
        table_name="admin_risk_flags",
    )
    op.drop_table("admin_risk_flags")

    op.drop_index(
        op.f("ix_admin_verification_overrides_user_id"),
        table_name="admin_verification_overrides",
    )
    op.drop_index(
        op.f("ix_admin_verification_overrides_review_case_id"),
        table_name="admin_verification_overrides",
    )
    op.drop_index(
        op.f("ix_admin_verification_overrides_overridden_by"),
        table_name="admin_verification_overrides",
    )
    op.drop_index(
        op.f("ix_admin_verification_overrides_idempotency_key"),
        table_name="admin_verification_overrides",
    )
    op.drop_table("admin_verification_overrides")
