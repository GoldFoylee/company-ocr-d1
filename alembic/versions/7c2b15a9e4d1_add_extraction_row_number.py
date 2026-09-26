"""add extraction row number

Revision ID: 7c2b15a9e4d1
Revises: 09f26b87ba86
Create Date: 2026-09-25 13:00:00.000000

"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c2b15a9e4d1"
down_revision: str | None = "09f26b87ba86"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROW_NUMBER_PATTERN = re.compile(
    r"(?:^|[\\/])row(?P<row_number>\d+)_[^\\/]+[.]jpg$",
    re.IGNORECASE,
)


def _row_number_from_crop_ref(image_crop_ref: str) -> int:
    """Recover the physical row encoded by pipeline crop filenames.

    Records predating the row-aware pipeline can have arbitrary synthetic crop
    references. They remain addressable as row 1 instead of blocking the
    migration; every real pipeline path uses the ``rowNN_field.jpg`` contract.
    """
    match = _ROW_NUMBER_PATTERN.search(image_crop_ref)
    if match is None:
        return 1
    return max(1, int(match.group("row_number")))


def upgrade() -> None:
    op.add_column("extractions", sa.Column("row_number", sa.Integer(), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, image_crop_ref FROM extractions ORDER BY id")
    ).mappings()
    updates = [
        {
            "extraction_id": row["id"],
            "row_number": _row_number_from_crop_ref(row["image_crop_ref"]),
        }
        for row in rows
    ]
    if updates:
        connection.execute(
            sa.text(
                "UPDATE extractions SET row_number = :row_number "
                "WHERE id = :extraction_id"
            ),
            updates,
        )

    op.alter_column("extractions", "row_number", existing_type=sa.Integer(), nullable=False)
    op.create_check_constraint(
        "ck_extractions_row_number_positive",
        "extractions",
        "row_number >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_extractions_row_number_positive",
        "extractions",
        type_="check",
    )
    op.drop_column("extractions", "row_number")
