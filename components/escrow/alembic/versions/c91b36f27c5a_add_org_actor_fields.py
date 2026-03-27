"""add org actor fields

Revision ID: c91b36f27c5a
Revises: a4e7b719dd74
Create Date: 2026-03-28 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c91b36f27c5a"
down_revision: Union[str, Sequence[str], None] = "a4e7b719dd74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "escrows",
        sa.Column("initiator_actor_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "escrows",
        sa.Column("initiator_org_id", sa.Uuid(as_uuid=True), nullable=True),
    )

    op.execute("UPDATE escrows SET initiator_actor_type = 'user'")

    op.alter_column("escrows", "initiator_actor_type", nullable=False)
    op.alter_column("escrows", "initiator_id", nullable=True)

    op.create_check_constraint(
        "ck_escrows_initiator_actor_type",
        "escrows",
        "initiator_actor_type IN ('user', 'organization')",
    )
    op.create_check_constraint(
        "ck_escrows_initiator_actor_consistency",
        "escrows",
        "((initiator_actor_type = 'user' AND initiator_id IS NOT NULL AND initiator_org_id IS NULL) OR (initiator_actor_type = 'organization' AND initiator_id IS NULL AND initiator_org_id IS NOT NULL))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_escrows_initiator_actor_consistency", "escrows", type_="check"
    )
    op.drop_constraint("ck_escrows_initiator_actor_type", "escrows", type_="check")

    op.execute(
        "UPDATE escrows SET initiator_id = initiator_org_id WHERE initiator_id IS NULL AND initiator_org_id IS NOT NULL"
    )

    op.alter_column("escrows", "initiator_id", nullable=False)
    op.drop_column("escrows", "initiator_org_id")
    op.drop_column("escrows", "initiator_actor_type")
