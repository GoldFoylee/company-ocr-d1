"""Assign validation failures only after checking which fields are verified.

A field can remain unflagged only when its own format/confidence checks pass and
every applicable cross-field check positively verifies it. If an operand is
unreadable, other fields needed by that check remain flagged as unverified.
Cross-field failures flag their implicated cells; a row warning supplements
those flags instead of replacing them.
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
    parsed_ds_rows: list[int] = []
    unreadable_ds_rows: list[int] = []
    parsed_date_rows: list[int] = []
    unreadable_date_rows: list[int] = []

    def fail(number: int, field: str, rule: str, reason: str) -> None:
        field_issues.setdefault((number, field), []).append(
            ValidationResult(rule, False, reason, number)
        )

    def warn(number: int, rule: str, reason: str) -> None:
        warnings.setdefault(number, []).append(ValidationResult(rule, False, reason, number))

    def could_not_verify(
        number: int, rule: str, fields: Sequence[str], unreadable: Sequence[str]
    ) -> None:
        for field in fields:
            if field in unreadable:
                continue
            for missing in unreadable:
                fail(number, field, rule, f"could not verify: {missing} unreadable")

    for number, row in enumerate(rows, start=1):
        ds_raw = row.ds_no.strip()
        if not ds_raw.isdecimal() or int(ds_raw) <= 0:
            fail(number, "ds_no", "unique_ds_no", f"unparseable DS.No value: {row.ds_no!r}")
            unreadable_ds_rows.append(number)
        else:
            parsed_ds_rows.append(number)
            ds = int(ds_raw)
            if ds in first_ds_row:
                first_row = first_ds_row[ds]
                reason = f"duplicate DS.No {ds} found at rows {first_row} and {number}"
                fail(
                    number, "ds_no", "unique_ds_no",
                    reason,
                )
                fail(first_row, "ds_no", "unique_ds_no", reason)
            else:
                first_ds_row[ds] = number

        normalized_date = canonicalize("date", row.date)
        if normalized_date is None:
            fail(number, "date", "date_format", f"unparseable date format: {row.date!r}")
            unreadable_date_rows.append(number)
        else:
            parsed_date_rows.append(number)
            parsed_date = date.fromisoformat(normalized_date)
            if previous_date is not None and parsed_date < previous_date[1]:
                reason = (
                    f"date at row {number} ({parsed_date.isoformat()}) is earlier than "
                    f"row {previous_date[0]} ({previous_date[1].isoformat()})"
                )
                fail(
                    number, "date", "non_decreasing_dates",
                    reason,
                )
                fail(previous_date[0], "date", "non_decreasing_dates", reason)
            previous_date = (number, parsed_date)

        km_values: dict[str, Decimal] = {}
        km_fields = ("start_km", "close_km", "total_km")
        km_unreadable: list[str] = []
        for field, raw in (
            ("start_km", row.starting_km),
            ("close_km", row.closing_km),
            ("total_km", row.total_km),
        ):
            stripped = raw.strip()
            normalized = canonicalize(field, raw)
            if not _KM_FORMAT.fullmatch(stripped) or normalized is None:
                fail(number, field, "kilometre_format", f"unparseable {field} value: {raw!r}")
                km_unreadable.append(field)
            else:
                km_values[field] = (
                    Decimal(stripped.replace(",", "")) if "." in stripped else Decimal(normalized)
                )
        if km_unreadable:
            could_not_verify(number, "kilometre_total", km_fields, km_unreadable)
        if len(km_values) == 3:
            computed = km_values["close_km"] - km_values["start_km"]
            if computed != km_values["total_km"]:
                reason = (
                    f"kilometre mismatch: computed {computed}, "
                    f"reported {km_values['total_km']}"
                )
                for field in km_fields:
                    fail(number, field, "kilometre_total", reason)
                warn(
                    number, "kilometre_total",
                    reason,
                )

        clock_values: dict[str, int] = {}
        time_fields = ("start_time", "close_time", "total_time")
        time_unreadable: list[str] = []
        for field, raw in (("start_time", row.start_time), ("close_time", row.closing_time)):
            normalized = canonicalize(field, raw)
            if normalized is None:
                fail(number, field, "time_format", f"unparseable {field} format: {raw!r}")
                time_unreadable.append(field)
            else:
                hours, minutes = map(int, normalized.split(":"))
                clock_values[field] = hours * 60 + minutes
        total_time = canonicalize("total_time", row.total_time)
        if total_time is None:
            fail(
                number, "total_time", "total_time_category",
                f"unrecognized total_time category: {row.total_time!r}; expected 0h, 12h, or 1d",
            )
            time_unreadable.append("total_time")
        if time_unreadable:
            could_not_verify(number, "time_total", time_fields, time_unreadable)
        elif total_time is not None and row.total_time.strip().upper() != total_time:
            # A supported alias establishes the category, not that the clocks
            # agree with it. The current rules check order but do not check
            # exact clock-duration consistency, so keep all operands in review.
            reason = (
                f"could not verify: normalized total_time {row.total_time!r}; "
                "clock-duration consistency is not checked"
            )
            for field in time_fields:
                fail(number, field, "time_total", reason)
        if len(clock_values) == 2 and clock_values["close_time"] < clock_values["start_time"]:
            reason = "close_time is earlier than start_time"
            for field in time_fields:
                fail(number, field, "time_total", reason)
            warn(number, "time_total", reason)
        if (
            len(clock_values) == 2
            and total_time == "12H"
            and clock_values["close_time"] == clock_values["start_time"]
        ):
            reason = "12h total_time has identical start and close clocks"
            for field in time_fields:
                fail(number, field, "time_total", reason)
            warn(number, "time_total", reason)

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

    # Uniqueness is global: an unreadable DS value could duplicate any parsed
    # DS cell. Date ordering is adjacent: only the readable neighbours of an
    # unreadable date lose their comparison evidence.
    for missing_row in unreadable_ds_rows:
        for row_number in parsed_ds_rows:
            fail(
                row_number, "ds_no", "unique_ds_no",
                f"could not verify: ds_no unreadable at row {missing_row}",
            )
    parsed_date_set = set(parsed_date_rows)
    for missing_row in unreadable_date_rows:
        for row_number in (missing_row - 1, missing_row + 1):
            if row_number in parsed_date_set:
                fail(
                    row_number, "date", "non_decreasing_dates",
                    "could not verify: date unreadable",
                )

    return ScopedValidation(
        {key: tuple(items) for key, items in field_issues.items()},
        {key: tuple(items) for key, items in warnings.items()},
    )
