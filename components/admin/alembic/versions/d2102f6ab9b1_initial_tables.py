"""Initial tables

Revision ID: d2102f6ab9b1
Revises:
Create Date: 2026-03-29 10:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2102f6ab9b1"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "admin_action_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("admin_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "performed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_action_logs_action"),
        "admin_action_logs",
        ["action"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_action_logs_admin_id"),
        "admin_action_logs",
        ["admin_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_action_logs_target_id"),
        "admin_action_logs",
        ["target_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_action_logs_target_type"),
        "admin_action_logs",
        ["target_type"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_admin_action_logs_target_type"), table_name="admin_action_logs")
    op.drop_index(op.f("ix_admin_action_logs_target_id"), table_name="admin_action_logs")
    op.drop_index(op.f("ix_admin_action_logs_admin_id"), table_name="admin_action_logs")
    op.drop_index(op.f("ix_admin_action_logs_action"), table_name="admin_action_logs")
    op.drop_table("admin_action_logs")