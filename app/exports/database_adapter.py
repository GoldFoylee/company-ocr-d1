"""Adapt persisted OCR/review records to the billing workbook input contract."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Extraction, Sheet

_DATE_FORMATS: Final = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")
_CLOCK_RE: Final = re.compile(r"^(?P<hours>\d{1,2}):(?P<minutes>\d{2})(?::(?P<seconds>\d{2}))?$")
_DURATION_RE: Final = re.compile(
    r"^(?:(?P<days>\d+)d|(?P<hours>\d+(?:\.\d+)?)h|"
    r"(?P<clock_hours>\d{1,3}):(?P<minutes>\d{2})(?::(?P<seconds>\d{2}))?)$"
)
_EXPORTED_FIELDS: Final = frozenset(
    {
        "ds_no",
        "date",
        "start_time",
        "start_km",
        "close_time",
        "close_km",
        "total_km",
        "total_time",
        "toll",
        "parking",
        "journey_details",
    }
)
_REQUIRED_FIELDS: Final = frozenset(
    {"date", "start_time", "start_km", "close_time", "close_km", "total_time"}
)


class SheetExportNotFoundError(LookupError):
    """Raised when an export is requested for an unknown sheet."""


class SheetExportDataError(ValueError):
    """Raised when persisted effective values cannot produce a valid workbook."""


def normalize_billing_date(value: object) -> date:
    """Return a real date from the formats accepted by the OCR validator."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    normalized = str(value).strip()
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date value: {value!r}")


def normalize_billing_clock(value: object) -> time:
    """Return a real time value from OCR clock text."""
    if isinstance(value, datetime):
        return value.time().replace(tzinfo=None)
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    normalized = str(value).strip().replace(".", ":")
    match = _CLOCK_RE.fullmatch(normalized)
    if match is None:
        raise ValueError(f"Unsupported clock value: {value!r}")
    try:
        return time(
            int(match.group("hours")),
            int(match.group("minutes")),
            int(match.group("seconds") or 0),
        )
    except ValueError as exc:
        raise ValueError(f"Unsupported clock value: {value!r}") from exc


def normalize_billing_duration(value: object) -> str:
    """Normalize duration text while retaining elapsed whole-day information."""
    normalized = re.sub(r"\s+", "", str(value)).lower()
    match = _DURATION_RE.fullmatch(normalized)
    if match is None:
        raise ValueError(f"Unsupported duration value: {value!r}")
    if match.group("minutes") is not None and int(match.group("minutes")) > 59:
        raise ValueError(f"Unsupported duration value: {value!r}")
    if match.group("seconds") is not None and int(match.group("seconds")) > 59:
        raise ValueError(f"Unsupported duration value: {value!r}")
    return normalized


def normalize_billing_number(
    value: object,
    *,
    field_name: str,
    required: bool = True,
) -> int | float | None:
    """Return a typed finite number, preserving optional blanks as missing."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"Missing required {field_name} value")
        return None
    if isinstance(value, bool):
        raise ValueError(f"Unsupported {field_name} value: {value!r}")
    normalized = str(value).strip().replace(",", "")
    try:
        parsed = Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Unsupported {field_name} value: {value!r}") from exc
    if not parsed.is_finite() or not math.isfinite(float(parsed)):
        raise ValueError(f"Unsupported {field_name} value: {value!r}")
    if parsed == parsed.to_integral_value():
        return int(parsed)
    return float(parsed)


def build_billing_source(db: Session, sheet_id: int) -> Mapping[str, Any]:
    """Build one existing export input mapping from persisted effective values."""
    sheet = db.get(Sheet, sheet_id)
    if sheet is None:
        raise SheetExportNotFoundError(f"Sheet with id {sheet_id} not found")

    extractions = db.scalars(
        select(Extraction)
        .where(
            Extraction.sheet_id == sheet_id,
            Extraction.field_name.in_(_EXPORTED_FIELDS),
        )
        .order_by(Extraction.row_number, Extraction.id)
    ).all()
    by_row: dict[int, dict[str, object]] = {}
    for extraction in extractions:
        row_values = by_row.setdefault(extraction.row_number, {})
        if extraction.field_name in row_values:
            raise SheetExportDataError(
                f"Row {extraction.row_number} has duplicate {extraction.field_name} values"
            )
        row_values[extraction.field_name] = (
            extraction.final_value
            if extraction.final_value is not None
            else extraction.raw_ocr_value
        )

    if not by_row:
        raise SheetExportDataError("Sheet has no exportable extraction rows")

    rows: list[dict[str, object]] = []
    for row_number, values in sorted(by_row.items()):
        missing = sorted(_REQUIRED_FIELDS - values.keys())
        if missing:
            raise SheetExportDataError(
                f"Row {row_number} is missing required field(s): {', '.join(missing)}"
            )
        try:
            row: dict[str, object] = {
                "date": normalize_billing_date(values["date"]),
                "start_time": normalize_billing_clock(values["start_time"]),
                "start_km": normalize_billing_number(
                    values["start_km"], field_name="start_km"
                ),
                "close_time": normalize_billing_clock(values["close_time"]),
                "close_km": normalize_billing_number(
                    values["close_km"], field_name="close_km"
                ),
                "total_time": normalize_billing_duration(values["total_time"]),
                "toll": normalize_billing_number(
                    values.get("toll"), field_name="toll", required=False
                ),
                "parking": normalize_billing_number(
                    values.get("parking"), field_name="parking", required=False
                ),
            }
            if "ds_no" in values:
                row["ds_no"] = values["ds_no"]
            if "total_km" in values:
                row["total_km"] = normalize_billing_number(
                    values["total_km"], field_name="total_km"
                )
            if "journey_details" in values:
                row["journey_details"] = values["journey_details"]
        except ValueError as exc:
            raise SheetExportDataError(f"Row {row_number}: {exc}") from exc
        rows.append(row)

    return {"sheet_id": str(sheet.id), "vehicle_no": sheet.vehicle, "rows": rows}
