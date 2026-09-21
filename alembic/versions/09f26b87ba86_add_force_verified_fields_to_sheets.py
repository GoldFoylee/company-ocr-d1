"""add_force_verified_fields_to_sheets

Revision ID: 09f26b87ba86
Revises: a68f091c305f
Create Date: 2026-09-21 09:18:25.688309

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "09f26b87ba86"
down_revision: str | None = "a68f091c305f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sheets",
        sa.Column(
            "force_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "sheets",
        sa.Column("force_verified_by", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sheets_force_verified_by_reviewers",
        "sheets",
        "reviewers",
        ["force_verified_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_sheets_force_verified_by"),
        "sheets",
        ["force_verified_by"],
        unique=False,
    )
    op.add_column(
        "sheets",
        sa.Column("force_verified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sheets", "force_verified_at")
    op.drop_index(op.f("ix_sheets_force_verified_by"), table_name="sheets")
    op.drop_constraint("fk_sheets_force_verified_by_reviewers", "sheets", type_="foreignkey")
    op.drop_column("sheets", "force_verified_by")
    op.drop_column("sheets", "force_verified")
