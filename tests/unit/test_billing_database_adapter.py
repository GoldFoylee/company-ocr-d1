"""Unit coverage for database-value normalization used by billing exports."""

from datetime import date, time

import pytest

from app.exports.database_adapter import (
    normalize_billing_clock,
    normalize_billing_date,
    normalize_billing_duration,
    normalize_billing_number,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("2026-08-01", date(2026, 8, 1)),
        ("01/08/2026", date(2026, 8, 1)),
        ("01-08-2026", date(2026, 8, 1)),
        ("01.08.2026", date(2026, 8, 1)),
    ],
)
def test_normalize_billing_date_accepts_pipeline_formats(
    source: str, expected: date
) -> None:
    assert normalize_billing_date(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [("8.05", time(8, 5)), ("08:05", time(8, 5)), ("08:05:30", time(8, 5, 30))],
)
def test_normalize_billing_clock_returns_real_time(source: str, expected: time) -> None:
    assert normalize_billing_clock(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [("1d", "1d"), ("12 H", "12h"), ("38:30", "38:30"), ("1.5h", "1.5h")],
)
def test_normalize_billing_duration_preserves_elapsed_day_information(
    source: str, expected: str
) -> None:
    assert normalize_billing_duration(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [("23,695", 23695), ("75.50", 75.5), (0, 0), (" 40 ", 40)],
)
def test_normalize_billing_number_returns_typed_numeric_values(
    source: object, expected: int | float
) -> None:
    assert normalize_billing_number(source, field_name="test") == expected


@pytest.mark.parametrize(
    ("normalizer", "source"),
    [
        (normalize_billing_date, "not-a-date"),
        (normalize_billing_clock, "29:90"),
        (normalize_billing_duration, "many hours"),
    ],
)
def test_text_normalizers_reject_invalid_values(normalizer: object, source: str) -> None:
    with pytest.raises(ValueError):
        normalizer(source)  # type: ignore[operator]


def test_numeric_normalizer_allows_optional_blank_but_rejects_required_blank() -> None:
    assert normalize_billing_number("", field_name="toll", required=False) is None
    with pytest.raises(ValueError, match="start_km"):
        normalize_billing_number("", field_name="start_km")
