"""Validate raw text values extracted from vehicle-log rows.

This module operates on text only. It deliberately has no dependency on OCR or image code.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Final

DEFAULT_TIME_TOLERANCE: Final = timedelta(minutes=30)

_DATE_FORMATS: Final = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")


@dataclass(frozen=True)
class ExtractedRowValues:
    """Raw text values for one already-extracted sheet row."""

    ds_no: str
    date: str
    starting_km: str
    closing_km: str
    total_km: str
    start_time: str
    closing_time: str
    total_time: str


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of one business-rule check."""

    rule: str
    passed: bool
    reason: str
    row_number: int | None = None


class ValidationEngine:
    """Parse raw values and apply the Draft 1 row and sheet rules."""

    def __init__(self, time_tolerance: timedelta = DEFAULT_TIME_TOLERANCE) -> None:
        if time_tolerance < timedelta(0):
            raise ValueError("time_tolerance must not be negative")
        self.time_tolerance = time_tolerance

    def validate_kilometres(
        self, row: ExtractedRowValues, row_number: int | None = None
    ) -> ValidationResult:
        """Check that closing kilometres minus starting kilometres equals the total."""
        parsed_values: dict[str, Decimal] = {}
        for field_name in ("starting_km", "closing_km", "total_km"):
            raw_value = getattr(row, field_name)
            value = _parse_decimal(raw_value)
            if value is None:
                return ValidationResult(
                    rule="kilometre_total",
                    passed=False,
                    reason=f"unparseable {field_name} value: {raw_value!r}",
                    row_number=row_number,
                )
            parsed_values[field_name] = value

        computed_total = parsed_values["closing_km"] - parsed_values["starting_km"]
        reported_total = parsed_values["total_km"]
        if computed_total != reported_total:
            return ValidationResult(
                rule="kilometre_total",
                passed=False,
                reason=(
                    "kilometre mismatch: "
                    f"computed {_format_decimal(computed_total)}, "
                    f"reported {_format_decimal(reported_total)}"
                ),
                row_number=row_number,
            )

        return ValidationResult(
            rule="kilometre_total",
            passed=True,
            reason=(
                f"{row.closing_km.strip()} - {row.starting_km.strip()} "
                f"= {row.total_km.strip()}"
            ),
            row_number=row_number,
        )

    def validate_time(
        self, row: ExtractedRowValues, row_number: int | None = None
    ) -> ValidationResult:
        """Check elapsed time against the reported total using the configured tolerance."""
        parsed_values: dict[str, int] = {}
        for field_name in ("start_time", "closing_time", "total_time"):
            raw_value = getattr(row, field_name)
            value = _parse_time(raw_value)
            if value is None:
                return ValidationResult(
                    rule="time_total",
                    passed=False,
                    reason=f"unparseable {field_name} format: {raw_value!r}",
                    row_number=row_number,
                )
            parsed_values[field_name] = value

        elapsed_seconds = parsed_values["closing_time"] - parsed_values["start_time"]
        if elapsed_seconds < 0:
            return ValidationResult(
                rule="time_total",
                passed=False,
                reason="closing_time is earlier than start_time",
                row_number=row_number,
            )

        reported_seconds = parsed_values["total_time"]
        difference_seconds = abs(elapsed_seconds - reported_seconds)
        tolerance_seconds = int(self.time_tolerance.total_seconds())
        tolerance_label = _format_tolerance(self.time_tolerance)

        if difference_seconds > tolerance_seconds:
            return ValidationResult(
                rule="time_total",
                passed=False,
                reason=(
                    f"time mismatch: elapsed {_format_time(elapsed_seconds)}, "
                    f"reported {_format_time(reported_seconds)}; difference "
                    f"{_format_time(difference_seconds)} exceeds ±{tolerance_label}"
                ),
                row_number=row_number,
            )

        return ValidationResult(
            rule="time_total",
            passed=True,
            reason=(
                f"elapsed {_format_time(elapsed_seconds)} and reported "
                f"{_format_time(reported_seconds)} are within ±{tolerance_label}"
            ),
            row_number=row_number,
        )

    def validate_unique_ds_numbers(
        self, rows: Sequence[ExtractedRowValues]
    ) -> ValidationResult:
        """Check that every parseable DS.No occurs only once in the sheet."""
        first_row_by_number: dict[int, int] = {}
        for row_number, row in enumerate(rows, start=1):
            ds_number = _parse_ds_number(row.ds_no)
            if ds_number is None:
                return ValidationResult(
                    rule="unique_ds_no",
                    passed=False,
                    reason=f"unparseable DS.No value at row {row_number}: {row.ds_no!r}",
                )
            if ds_number in first_row_by_number:
                return ValidationResult(
                    rule="unique_ds_no",
                    passed=False,
                    reason=(
                        f"duplicate DS.No {ds_number} found at rows "
                        f"{first_row_by_number[ds_number]} and {row_number}"
                    ),
                )
            first_row_by_number[ds_number] = row_number

        return ValidationResult(
            rule="unique_ds_no",
            passed=True,
            reason="all DS.No values are unique",
        )

    def validate_non_decreasing_dates(
        self, rows: Sequence[ExtractedRowValues]
    ) -> ValidationResult:
        """Check that sheet dates do not move backwards as row sequence increases."""
        previous_date: date | None = None
        previous_row_number: int | None = None

        for row_number, row in enumerate(rows, start=1):
            parsed_date = _parse_date(row.date)
            if parsed_date is None:
                return ValidationResult(
                    rule="non_decreasing_dates",
                    passed=False,
                    reason=f"unparseable date format at row {row_number}: {row.date!r}",
                )
            if previous_date is not None and parsed_date < previous_date:
                return ValidationResult(
                    rule="non_decreasing_dates",
                    passed=False,
                    reason=(
                        f"date at row {row_number} ({parsed_date.isoformat()}) is earlier than "
                        f"row {previous_row_number} ({previous_date.isoformat()})"
                    ),
                )
            previous_date = parsed_date
            previous_row_number = row_number

        return ValidationResult(
            rule="non_decreasing_dates",
            passed=True,
            reason="sheet dates are non-decreasing",
        )

    def validate_sheet(
        self, rows: Sequence[ExtractedRowValues]
    ) -> tuple[ValidationResult, ...]:
        """Run row-level checks followed by sheet-level sequence checks."""
        results: list[ValidationResult] = []
        for row_number, row in enumerate(rows, start=1):
            results.append(self.validate_kilometres(row, row_number=row_number))
            results.append(self.validate_time(row, row_number=row_number))

        results.append(self.validate_unique_ds_numbers(rows))
        results.append(self.validate_non_decreasing_dates(rows))
        return tuple(results)


def _parse_decimal(raw_value: str) -> Decimal | None:
    try:
        value = Decimal(raw_value.strip())
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _parse_time(raw_value: str) -> int | None:
    parts = raw_value.strip().split(":")
    if len(parts) not in (2, 3) or not all(part.isdecimal() for part in parts):
        return None

    hours, minutes = int(parts[0]), int(parts[1])
    seconds = int(parts[2]) if len(parts) == 3 else 0
    if hours > 23 or minutes > 59 or seconds > 59:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _parse_ds_number(raw_value: str) -> int | None:
    normalized = raw_value.strip()
    if not normalized.isdecimal():
        return None
    value = int(normalized)
    return value if value > 0 else None


def _parse_date(raw_value: str) -> date | None:
    normalized = raw_value.strip()
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    return None


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")


def _format_time(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if seconds:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}"


def _format_tolerance(tolerance: timedelta) -> str:
    total_seconds = int(tolerance.total_seconds())
    if total_seconds % 60 == 0:
        return f"{total_seconds // 60} minutes"
    return _format_time(total_seconds)
