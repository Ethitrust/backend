"""Add admin foundation tables

Revision ID: 7c4a6b4f3d1e
Revises: d2102f6ab9b1
Create Date: 2026-03-29 18:05:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c4a6b4f3d1e"
down_revision: Union[str, Sequence[str], None] = "d2102f6ab9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_review_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("subject_type", sa.String(length=50), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("assignee_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("escalated_from_case_id", sa.UUID(), nullable=True),
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
        op.f("ix_admin_review_cases_assignee_id"),
        "admin_review_cases",
        ["assignee_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_review_cases_created_by"),
        "admin_review_cases",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_review_cases_priority"),
        "admin_review_cases",
        ["priority"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_review_cases_status"),
        "admin_review_cases",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_review_cases_subject_id"),
        "admin_review_cases",
        ["subject_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_review_cases_subject_type"),
        "admin_review_cases",
        ["subject_type"],
        unique=False,
    )

    op.create_table(
        "admin_moderation_notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["admin_review_cases.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_moderation_notes_case_id"),
        "admin_moderation_notes",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_moderation_notes_created_by"),
        "admin_moderation_notes",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_moderation_notes_target_id"),
        "admin_moderation_notes",
        ["target_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_moderation_notes_target_type"),
        "admin_moderation_notes",
        ["target_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_moderation_notes_visibility"),
        "admin_moderation_notes",
        ["visibility"],
        unique=False,
    )

    op.create_table(
        "admin_saved_views",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("is_shared", sa.Boolean(), nullable=False),
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
        op.f("ix_admin_saved_views_module"),
        "admin_saved_views",
        ["module"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_saved_views_owner_id"),
        "admin_saved_views",
        ["owner_id"],
        unique=False,
    )

    op.create_table(
        "admin_report_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("report_type", sa.String(length=50), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("result_url", sa.String(length=500), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admin_report_jobs_report_type"),
        "admin_report_jobs",
        ["report_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_report_jobs_requested_by"),
        "admin_report_jobs",
        ["requested_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_report_jobs_status"),
        "admin_report_jobs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_report_jobs_status"), table_name="admin_report_jobs")
    op.drop_index(
        op.f("ix_admin_report_jobs_requested_by"), table_name="admin_report_jobs"
    )
    op.drop_index(
        op.f("ix_admin_report_jobs_report_type"), table_name="admin_report_jobs"
    )
    op.drop_table("admin_report_jobs")

    op.drop_index(op.f("ix_admin_saved_views_owner_id"), table_name="admin_saved_views")
    op.drop_index(op.f("ix_admin_saved_views_module"), table_name="admin_saved_views")
    op.drop_table("admin_saved_views")

    op.drop_index(
        op.f("ix_admin_moderation_notes_visibility"),
        table_name="admin_moderation_notes",
    )
    op.drop_index(
        op.f("ix_admin_moderation_notes_target_type"),
        table_name="admin_moderation_notes",
    )
    op.drop_index(
        op.f("ix_admin_moderation_notes_target_id"), table_name="admin_moderation_notes"
    )
    op.drop_index(
        op.f("ix_admin_moderation_notes_created_by"),
        table_name="admin_moderation_notes",
    )
    op.drop_index(
        op.f("ix_admin_moderation_notes_case_id"), table_name="admin_moderation_notes"
    )
    op.drop_table("admin_moderation_notes")

    op.drop_index(
        op.f("ix_admin_review_cases_subject_type"), table_name="admin_review_cases"
    )
    op.drop_index(
        op.f("ix_admin_review_cases_subject_id"), table_name="admin_review_cases"
    )
    op.drop_index(op.f("ix_admin_review_cases_status"), table_name="admin_review_cases")
    op.drop_index(
        op.f("ix_admin_review_cases_priority"), table_name="admin_review_cases"
    )
    op.drop_index(
        op.f("ix_admin_review_cases_created_by"), table_name="admin_review_cases"
    )
    op.drop_index(
        op.f("ix_admin_review_cases_assignee_id"), table_name="admin_review_cases"
    )
    op.drop_table("admin_review_cases")
