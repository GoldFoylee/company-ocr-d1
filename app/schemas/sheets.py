"""Request and response schemas for sheet ingestion and tabular review."""

from datetime import date, datetime

from pydantic import BaseModel


class SheetUploadResponse(BaseModel):
    """Persisted result returned after synchronous OCR processing."""

    sheet_id: int
    row_count: int
    extraction_count: int
    status: str


class SheetSummaryResponse(BaseModel):
    """One uploaded sheet available in the review switcher."""

    id: int
    vehicle: str
    branch: str
    date: date
    status: str
    force_verified: bool


class SheetColumnResponse(BaseModel):
    """One physical form column, in display order."""

    name: str
    label: str
    excluded: bool = False


class SheetCellResponse(BaseModel):
    """One extraction projected into the physical form grid."""

    id: int | None
    row_number: int
    field_name: str
    raw_ocr_value: str | None
    final_value: str | None
    effective_value: str | None
    confidence: float | None
    rule_flag: bool
    rule_flag_reason: str | None
    reviewed_at: datetime | None
    needs_review: bool
    crop_url: str | None
    excluded: bool = False
    missing: bool = False


class SheetRowResponse(BaseModel):
    """One physical data row with all twelve columns present."""

    row_number: int
    cells: list[SheetCellResponse]


class SheetDetailResponse(SheetSummaryResponse):
    """Sheet metadata and its complete physical review grid."""

    columns: list[SheetColumnResponse]
    rows: list[SheetRowResponse]
