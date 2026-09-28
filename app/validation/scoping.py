"""Assign validation failures to cells only when the evidence identifies one.

Arithmetic and clock-order contradictions identify a row, but cannot tell which
of the valid-looking inputs OCR got wrong. They are retained as row warnings.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.validation.canonicalization import canonicalize
from app.validation.engine import ExtractedRowValues, ValidationResult

_KM_FORMAT = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?\Z")
_AMOUNT_FORMAT = re.compile(r"(?:[₹$]|Rs\.?\s*)?\s*\d+(?:,\d{3})*(?:\.\d+)?\Z", re.I)


@dataclass(frozen=True)
class ScopedValidation:
    field_failures: dict[tuple[int, str], tuple[ValidationResult, ...]]
    row_warnings: dict[int, tuple[ValidationResult, ...]]

    def for_field(self, row_number: int, field_name: str) -> tuple[ValidationResult, ...]:
        return self.field_failures.get((row_number, field_name), ())


def scope_sheet(
    rows: Sequence[ExtractedRowValues],
    other_fields: Sequence[Mapping[str, str]] | None = None,
) -> ScopedValidation:
    """Validate OCR input with shared canonical forms, retaining original text.

    Row numbers are one-based. ``other_fields`` may provide Toll and Parking
    values, which have their own field-level numeric/blank check.
    """
    if other_fields is not None and len(other_fields) != len(rows):
        raise ValueError("other_fields must have one mapping per row")

    field_issues: dict[tuple[int, str], list[ValidationResult]] = {}
    warnings: dict[int, list[ValidationResult]] = {}
    first_ds_row: dict[int, int] = {}
    previous_date: tuple[int, date] | None = None

    def fail(number: int, field: str, rule: str, reason: str) -> None:
        field_issues.setdefault((number, field), []).append(
            ValidationResult(rule, False, reason, number)
        )

    def warn(number: int, rule: str, reason: str) -> None:
        warnings.setdefault(number, []).append(ValidationResult(rule, False, reason, number))

    for number, row in enumerate(rows, start=1):
        ds_raw = row.ds_no.strip()
        if not ds_raw.isdecimal() or int(ds_raw) <= 0:
            fail(number, "ds_no", "unique_ds_no", f"unparseable DS.No value: {row.ds_no!r}")
        else:
            ds = int(ds_raw)
            if ds in first_ds_row:
                fail(
                    number, "ds_no", "unique_ds_no",
                    f"duplicate DS.No {ds} found at rows {first_ds_row[ds]} and {number}",
                )
            else:
                first_ds_row[ds] = number

        normalized_date = canonicalize("date", row.date)
        if normalized_date is None:
            fail(number, "date", "date_format", f"unparseable date format: {row.date!r}")
        else:
            parsed_date = date.fromisoformat(normalized_date)
            if previous_date is not None and parsed_date < previous_date[1]:
                fail(
                    number, "date", "non_decreasing_dates",
                    f"date at row {number} ({parsed_date.isoformat()}) is earlier than "
                    f"row {previous_date[0]} ({previous_date[1].isoformat()})",
                )
            previous_date = (number, parsed_date)

        km_values: dict[str, Decimal] = {}
        for field, raw in (
            ("start_km", row.starting_km),
            ("close_km", row.closing_km),
            ("total_km", row.total_km),
        ):
            stripped = raw.strip()
            normalized = canonicalize(field, raw)
            if not _KM_FORMAT.fullmatch(stripped) or normalized is None:
                fail(number, field, "kilometre_format", f"unparseable {field} value: {raw!r}")
            else:
                km_values[field] = (
                    Decimal(stripped.replace(",", "")) if "." in stripped else Decimal(normalized)
                )
        if len(km_values) == 3:
            computed = km_values["close_km"] - km_values["start_km"]
            if computed != km_values["total_km"]:
                warn(
                    number, "kilometre_total",
                    f"kilometre mismatch: computed {computed}, reported {km_values['total_km']}",
                )

        clock_values: dict[str, int] = {}
        for field, raw in (("start_time", row.start_time), ("close_time", row.closing_time)):
            normalized = canonicalize(field, raw)
            if normalized is None:
                fail(number, field, "time_format", f"unparseable {field} format: {raw!r}")
            else:
                hours, minutes = map(int, normalized.split(":"))
                clock_values[field] = hours * 60 + minutes
        total_time = canonicalize("total_time", row.total_time)
        if total_time is None:
            fail(
                number, "total_time", "total_time_category",
                f"unrecognized total_time category: {row.total_time!r}; expected 0h, 12h, or 1d",
            )
        if len(clock_values) == 2 and clock_values["close_time"] < clock_values["start_time"]:
            warn(number, "time_total", "close_time is earlier than start_time")
        if (
            len(clock_values) == 2
            and total_time == "12H"
            and clock_values["close_time"] == clock_values["start_time"]
        ):
            warn(number, "time_total", "12h total_time has identical start and close clocks")

        if other_fields is not None:
            for field in ("toll", "parking"):
                amount_raw = other_fields[number - 1].get(field)
                if (
                    amount_raw is not None
                    and amount_raw.strip()
                    and not _AMOUNT_FORMAT.fullmatch(amount_raw.strip())
                ):
                    fail(
                        number, field, "amount_format",
                        f"unparseable {field} value: {amount_raw!r}",
                    )

    return ScopedValidation(
        {key: tuple(items) for key, items in field_issues.items()},
        {key: tuple(items) for key, items in warnings.items()},
    )
