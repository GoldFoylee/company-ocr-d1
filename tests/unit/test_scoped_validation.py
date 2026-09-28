"""A failed rule should identify a cell or remain a row warning."""

from dataclasses import replace

from app.validation.engine import ExtractedRowValues
from app.validation.scoping import scope_sheet


def row(**changes: str) -> ExtractedRowValues:
    return replace(
        ExtractedRowValues(
            ds_no="1", date="2026-08-01", starting_km="1000",
            closing_km="1150", total_km="150", start_time="08:00",
            closing_time="20:00", total_time="12h",
        ),
        **changes,
    )


def test_one_unparseable_field_does_not_flag_its_valid_neighbours() -> None:
    scoped = scope_sheet([row(starting_km="bad", closing_time="garbled")])
    assert set(scoped.field_failures) == {(1, "start_km"), (1, "close_time")}
    assert scoped.row_warnings == {}


def test_normalization_accepts_supported_formats_without_changing_source() -> None:
    source = row(date="1/8/26", start_time="8:00 am", total_time="12")
    scoped = scope_sheet([source])
    assert scoped.field_failures == {}
    assert scoped.row_warnings == {}
    assert source.date == "1/8/26"
    assert source.total_time == "12"


def test_ambiguous_cross_field_mismatch_is_a_row_warning() -> None:
    scoped = scope_sheet([row(total_km="149", closing_time="07:00")])
    assert scoped.field_failures == {}
    assert {r.rule for r in scoped.row_warnings[1]} == {"kilometre_total", "time_total"}


def test_twelve_hour_category_with_identical_clocks_is_a_row_warning() -> None:
    scoped = scope_sheet([row(closing_time="08:00")])
    assert scoped.field_failures == {}
    assert any("identical" in result.reason for result in scoped.row_warnings[1])


def test_sheet_rules_flag_only_offending_ds_and_date_cells() -> None:
    scoped = scope_sheet([
        row(),
        row(ds_no="1", date="2026-08-02"),
        row(ds_no="3 7", date="unreadable"),
        row(ds_no="4", date="2026-07-31"),
    ])
    assert (1, "ds_no") not in scoped.field_failures
    assert (1, "date") not in scoped.field_failures
    assert (2, "ds_no") in scoped.field_failures
    assert (3, "ds_no") in scoped.field_failures
    assert (3, "date") in scoped.field_failures
    assert (4, "date") in scoped.field_failures
    assert (2, "date") not in scoped.field_failures


def test_merged_km_and_route_text_in_toll_are_not_accepted_as_numbers() -> None:
    scoped = scope_sheet([row(closing_km="172807 137")], [{"toll": "Airport to hotel"}])
    assert (1, "close_km") in scoped.field_failures
    assert (1, "toll") in scoped.field_failures
