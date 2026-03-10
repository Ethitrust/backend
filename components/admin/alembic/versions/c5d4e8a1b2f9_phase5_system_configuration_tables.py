"""Add phase 5 system configuration tables

Revision ID: c5d4e8a1b2f9
Revises: f3a1d9b2c4e7
Create Date: 2026-03-29 22:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d4e8a1b2f9"
down_revision: Union[str, Sequence[str], None] = "f3a1d9b2c4e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_system_configs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("config_key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=False),
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
        op.f("ix_admin_system_configs_config_key"),
        "admin_system_configs",
        ["config_key"],
        unique=True,
    )
    op.create_index(
        op.f("ix_admin_system_configs_updated_by"),
        "admin_system_configs",
        ["updated_by"],
        unique=False,
    )

    op.create_table(
        "admin_system_config_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("config_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("previous_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("changed_by", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "config_key",
            "version",
            name="uq_admin_system_config_history_key_version",
        ),
    )
    op.create_index(
        op.f("ix_admin_system_config_history_action"),
        "admin_system_config_history",
        ["action"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_system_config_history_changed_by"),
        "admin_system_config_history",
        ["changed_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_system_config_history_config_key"),
        "admin_system_config_history",
        ["config_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_system_config_history_version"),
        "admin_system_config_history",
        ["version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admin_system_config_history_version"),
        table_name="admin_system_config_history",
    )
    op.drop_index(
        op.f("ix_admin_system_config_history_config_key"),
        table_name="admin_system_config_history",
    )
    op.drop_index(
        op.f("ix_admin_system_config_history_changed_by"),
        table_name="admin_system_config_history",
    )
    op.drop_index(
        op.f("ix_admin_system_config_history_action"),
        table_name="admin_system_config_history",
    )
    op.drop_table("admin_system_config_history")

    op.drop_index(
        op.f("ix_admin_system_configs_updated_by"), table_name="admin_system_configs"
    )
    op.drop_index(
        op.f("ix_admin_system_configs_config_key"), table_name="admin_system_configs"
    )
    op.drop_table("admin_system_configs")
