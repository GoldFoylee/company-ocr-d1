"""Read models for the sheet-oriented review interface."""

from typing import Final

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cropping.cells import FIELD_NAMES
from app.models import Extraction, Sheet
from app.schemas.sheets import (
    SheetCellResponse,
    SheetColumnResponse,
    SheetDetailResponse,
    SheetRowResponse,
    SheetSummaryResponse,
)

EXCLUDED_FIELD: Final = "guest_name"

FIELD_LABELS: Final[dict[str, str]] = {
    "ds_no": "DS No.",
    "date": "Date",
    "guest_name": "Guest Name",
    "start_time": "Start Time",
    "start_km": "Start KM",
    "close_time": "Close Time",
    "close_km": "Close KM",
    "total_km": "Total KM",
    "total_time": "Total Time",
    "toll": "Toll",
    "parking": "Parking",
    "journey_details": "Journey Details",
}


def list_sheets(db: Session) -> list[SheetSummaryResponse]:
    """Return every sheet for the sheet switcher, newest first."""
    sheets = db.scalars(select(Sheet).order_by(Sheet.id.desc())).all()
    return [
        SheetSummaryResponse(
            id=sheet.id,
            vehicle=sheet.vehicle,
            branch=sheet.branch,
            date=sheet.date,
            status=sheet.status,
            force_verified=sheet.force_verified,
        )
        for sheet in sheets
    ]


def get_sheet_detail(db: Session, sheet_id: int) -> SheetDetailResponse:
    """Return one sheet as rows with the physical twelve-column layout.

    ``guest_name`` is represented only by an empty excluded placeholder. The
    query and the projection both suppress malformed legacy guest records so
    recognized guest content can never cross the API boundary.
    """
    sheet = db.get(Sheet, sheet_id)
    if sheet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sheet with id {sheet_id} not found",
        )

    extractions = db.scalars(
        select(Extraction)
        .where(
            Extraction.sheet_id == sheet_id,
            Extraction.field_name != EXCLUDED_FIELD,
        )
        .order_by(Extraction.row_number, Extraction.id)
    ).all()

    by_row: dict[int, dict[str, Extraction]] = {}
    for extraction in extractions:
        if extraction.field_name == EXCLUDED_FIELD:
            continue
        by_row.setdefault(extraction.row_number, {}).setdefault(
            extraction.field_name, extraction
        )

    columns = [
        SheetColumnResponse(
            name=field_name,
            label=FIELD_LABELS[field_name],
            excluded=field_name == EXCLUDED_FIELD,
        )
        for field_name in FIELD_NAMES
    ]
    rows = [
        SheetRowResponse(
            row_number=row_number,
            cells=[
                _build_cell(
                    row_number=row_number,
                    field_name=field_name,
                    extraction=row_extractions.get(field_name),
                )
                for field_name in FIELD_NAMES
            ],
        )
        for row_number, row_extractions in sorted(by_row.items())
    ]

    return SheetDetailResponse(
        id=sheet.id,
        vehicle=sheet.vehicle,
        branch=sheet.branch,
        date=sheet.date,
        status=sheet.status,
        force_verified=sheet.force_verified,
        columns=columns,
        rows=rows,
    )


def _build_cell(
    *,
    row_number: int,
    field_name: str,
    extraction: Extraction | None,
) -> SheetCellResponse:
    if field_name == EXCLUDED_FIELD:
        return SheetCellResponse(
            id=None,
            row_number=row_number,
            field_name=field_name,
            raw_ocr_value=None,
            final_value=None,
            effective_value=None,
            confidence=None,
            rule_flag=False,
            rule_flag_reason=None,
            reviewed_at=None,
            needs_review=False,
            crop_url=None,
            excluded=True,
            missing=False,
        )

    if extraction is None:
        return SheetCellResponse(
            id=None,
            row_number=row_number,
            field_name=field_name,
            raw_ocr_value=None,
            final_value=None,
            effective_value=None,
            confidence=None,
            rule_flag=False,
            rule_flag_reason=None,
            reviewed_at=None,
            needs_review=False,
            crop_url=None,
            missing=True,
        )

    return SheetCellResponse(
        id=extraction.id,
        row_number=row_number,
        field_name=field_name,
        raw_ocr_value=extraction.raw_ocr_value,
        final_value=extraction.final_value,
        effective_value=(
            extraction.final_value
            if extraction.final_value is not None
            else extraction.raw_ocr_value
        ),
        confidence=extraction.confidence,
        rule_flag=extraction.rule_flag,
        rule_flag_reason=extraction.rule_flag_reason,
        reviewed_at=extraction.reviewed_at,
        needs_review=extraction.rule_flag and extraction.reviewed_at is None,
        crop_url=f"/review/crops/{extraction.id}",
    )
