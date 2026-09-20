"""tighten extraction audit fields

Revision ID: a68f091c305f
Revises: 2998a8f5bf87
Create Date: 2026-09-20 09:02:54.498660

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a68f091c305f"
down_revision: str | None = "2998a8f5bf87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "extractions",
        "image_crop_ref",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "extractions",
        "raw_ocr_value",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "extractions",
        "timestamp",
        new_column_name="created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
    )
    op.add_column(
        "extractions",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("extractions", "reviewed_at")
    op.alter_column(
        "extractions",
        "created_at",
        new_column_name="timestamp",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
    )
    op.alter_column(
        "extractions",
        "raw_ocr_value",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "extractions",
        "image_crop_ref",
        existing_type=sa.Text(),
        nullable=True,
    )
