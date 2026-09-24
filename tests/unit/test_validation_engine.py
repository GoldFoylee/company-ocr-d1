"""Business-rule tests for values extracted from a vehicle-log sheet."""

from dataclasses import replace

import pytest

from app.validation.engine import (
    TOTAL_TIME_CATEGORIES,
    ExtractedRowValues,
    ValidationEngine,
)


def make_row(**overrides: str) -> ExtractedRowValues:
    row = ExtractedRowValues(
        ds_no="1",
        date="2026-09-20",
        starting_km="1000",
        closing_km="1150",
        total_km="150",
        start_time="08:00",
        closing_time="10:00",
        total_time="12h",
    )
    return replace(row, **overrides)


def test_kilometre_check_accepts_matching_raw_numeric_strings() -> None:
    result = ValidationEngine().validate_kilometres(
        make_row(starting_km=" 1000.5 ", closing_km="1151.0", total_km="150.5"),
        row_number=3,
    )

    assert result.passed is True
    assert result.rule == "kilometre_total"
    assert result.row_number == 3
    assert "1151.0 - 1000.5 = 150.5" in result.reason


def test_kilometre_check_flags_mismatch() -> None:
    result = ValidationEngine().validate_kilometres(make_row(total_km="149"))

    assert result.passed is False
    assert "kilometre mismatch" in result.reason
    assert "computed 150" in result.reason
    assert "reported 149" in result.reason


@pytest.mark.parametrize("field", ["starting_km", "closing_km", "total_km"])
@pytest.mark.parametrize("value", ["", "not-a-number", "NaN", "Infinity"])
def test_kilometre_check_flags_unparseable_values(field: str, value: str) -> None:
    result = ValidationEngine().validate_kilometres(make_row(**{field: value}))

    assert result.passed is False
    assert result.reason == f"unparseable {field} value: {value!r}"


@pytest.mark.parametrize("total_time", sorted(TOTAL_TIME_CATEGORIES))
def test_time_check_accepts_every_known_total_time_category(total_time: str) -> None:
    result = ValidationEngine().validate_time(make_row(total_time=total_time))

    assert result.passed is True
    assert result.rule == "time_total"
    assert f"total_time category {total_time!r}" in result.reason


def test_time_check_strips_category_whitespace() -> None:
    result = ValidationEngine().validate_time(make_row(total_time=" 12h "))

    assert result.passed is True
    assert "total_time category '12h'" in result.reason


def test_time_check_accepts_seconds() -> None:
    result = ValidationEngine().validate_time(
        make_row(start_time="08:00:30", closing_time="10:00:30")
    )

    assert result.passed is True


@pytest.mark.parametrize("field", ["start_time", "closing_time"])
@pytest.mark.parametrize("value", ["", "25:00", "not-a-time"])
def test_time_check_flags_unparseable_values(field: str, value: str) -> None:
    result = ValidationEngine().validate_time(make_row(**{field: value}))

    assert result.passed is False
    assert result.reason == f"unparseable {field} format: {value!r}"


@pytest.mark.parametrize("value", ["", "02:00", "24h", "12H", "not-a-category"])
def test_time_check_flags_unknown_total_time_categories(value: str) -> None:
    result = ValidationEngine().validate_time(make_row(total_time=value))

    assert result.passed is False
    assert result.reason == (
        f"unrecognized total_time category: {value!r}; expected one of 0h, 12h, 1d"
    )


def test_time_check_flags_closing_time_before_start_time() -> None:
    result = ValidationEngine().validate_time(make_row(start_time="18:00", closing_time="08:00"))

    assert result.passed is False
    assert result.reason == "closing_time is earlier than start_time"


def test_duplicate_ds_number_check_accepts_unique_numbers() -> None:
    rows = [make_row(ds_no="1"), make_row(ds_no="2"), make_row(ds_no="3")]

    result = ValidationEngine().validate_unique_ds_numbers(rows)

    assert result.passed is True
    assert result.rule == "unique_ds_no"
    assert result.reason == "all DS.No values are unique"


def test_duplicate_ds_number_check_normalizes_leading_zeroes() -> None:
    rows = [make_row(ds_no="7"), make_row(ds_no="007")]

    result = ValidationEngine().validate_unique_ds_numbers(rows)

    assert result.passed is False
    assert result.reason == "duplicate DS.No 7 found at rows 1 and 2"


@pytest.mark.parametrize("value", ["", "ABC", "1.5", "0", "-1"])
def test_duplicate_ds_number_check_flags_unparseable_values(value: str) -> None:
    result = ValidationEngine().validate_unique_ds_numbers([make_row(ds_no=value)])

    assert result.passed is False
    assert result.reason == f"unparseable DS.No value at row 1: {value!r}"


def test_date_check_accepts_non_decreasing_dates_and_equal_dates() -> None:
    rows = [
        make_row(date="19/09/2026"),
        make_row(date="2026-09-20"),
        make_row(date="20-09-2026"),
        make_row(date="20.09.2026"),
    ]

    result = ValidationEngine().validate_non_decreasing_dates(rows)

    assert result.passed is True
    assert result.rule == "non_decreasing_dates"
    assert result.reason == "sheet dates are non-decreasing"


def test_date_check_flags_first_out_of_order_row() -> None:
    rows = [make_row(date="2026-09-20"), make_row(date="2026-09-19")]

    result = ValidationEngine().validate_non_decreasing_dates(rows)

    assert result.passed is False
    assert result.reason == "date at row 2 (2026-09-19) is earlier than row 1 (2026-09-20)"


@pytest.mark.parametrize("value", ["", "09/20/2026", "not-a-date"])
def test_date_check_flags_unparseable_values(value: str) -> None:
    result = ValidationEngine().validate_non_decreasing_dates([make_row(date=value)])

    assert result.passed is False
    assert result.reason == f"unparseable date format at row 1: {value!r}"


def test_empty_sheet_passes_sheet_level_checks() -> None:
    engine = ValidationEngine()

    duplicate_result = engine.validate_unique_ds_numbers([])
    date_result = engine.validate_non_decreasing_dates([])

    assert duplicate_result.passed is True
    assert date_result.passed is True


def test_validate_sheet_returns_row_and_sheet_results() -> None:
    rows = [make_row(ds_no="1"), make_row(ds_no="2", date="2026-09-21")]

    results = ValidationEngine().validate_sheet(rows)

    assert len(results) == 6
    assert [(result.rule, result.row_number) for result in results] == [
        ("kilometre_total", 1),
        ("time_total", 1),
        ("kilometre_total", 2),
        ("time_total", 2),
        ("unique_ds_no", None),
        ("non_decreasing_dates", None),
    ]
    assert all(result.passed for result in results)
