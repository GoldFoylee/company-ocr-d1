"""A value is clear only when its own and all applicable checks verified it."""

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


def reasons(scoped, field: str) -> list[str]:
    return [result.reason for result in scoped.for_field(1, field)]


def test_unreadable_km_operand_keeps_other_implicated_cells_flagged() -> None:
    scoped = scope_sheet([row(starting_km="bad")])

    assert (1, "start_km") in scoped.field_failures
    assert "unparseable start_km value" in " ".join(reasons(scoped, "start_km"))
    assert "could not verify: start_km unreadable" in " ".join(reasons(scoped, "close_km"))
    assert "could not verify: start_km unreadable" in " ".join(reasons(scoped, "total_km"))
    assert scoped.row_warnings == {}


def test_km_arithmetic_failure_flags_all_implicated_cells_and_warns() -> None:
    scoped = scope_sheet([row(total_km="149")])

    for field in ("start_km", "close_km", "total_km"):
        assert "kilometre mismatch" in " ".join(reasons(scoped, field))
    assert "kilometre_total" in {r.rule for r in scoped.row_warnings[1]}


def test_unreadable_time_operand_keeps_other_implicated_cells_flagged() -> None:
    scoped = scope_sheet([row(start_time="garbled")])

    assert "unparseable start_time" in " ".join(reasons(scoped, "start_time"))
    assert "could not verify: start_time unreadable" in " ".join(reasons(scoped, "close_time"))
    assert "could not verify: start_time unreadable" in " ".join(reasons(scoped, "total_time"))
    assert scoped.row_warnings == {}


def test_time_order_failure_flags_all_rule_operands() -> None:
    scoped = scope_sheet([row(closing_time="07:00")])

    for field in ("start_time", "close_time", "total_time"):
        assert "close_time is earlier than start_time" in " ".join(reasons(scoped, field))
    assert "time_total" in {r.rule for r in scoped.row_warnings[1]}


def test_normalization_accepts_supported_formats_without_changing_source() -> None:
    source = row(date="1/8/26", start_time="8:00 am", total_time="12")
    scoped = scope_sheet([source])
    assert set(scoped.field_failures) == {
        (1, "start_time"), (1, "close_time"), (1, "total_time")
    }
    assert all(
        "could not verify: normalized total_time" in " ".join(reasons(scoped, field))
        for field in ("start_time", "close_time", "total_time")
    )
    assert scoped.row_warnings == {}
    assert source.date == "1/8/26"
    assert source.total_time == "12"


def test_twelve_hour_category_with_identical_clocks_flags_all_three_fields() -> None:
    scoped = scope_sheet([row(closing_time="08:00")])

    for field in ("start_time", "close_time", "total_time"):
        assert "identical start and close clocks" in " ".join(reasons(scoped, field))
    assert "time_total" in {r.rule for r in scoped.row_warnings[1]}


def test_sheet_rules_flag_offenders_and_cells_with_unverified_comparisons() -> None:
    scoped = scope_sheet([
        row(),
        row(ds_no="1", date="2026-08-02"),
        row(ds_no="3 7", date="unreadable"),
        row(ds_no="4", date="2026-07-31"),
    ])
    assert (1, "ds_no") in scoped.field_failures
    assert "could not verify: ds_no unreadable at row 3" in " ".join(reasons(scoped, "ds_no"))
    assert (1, "date") not in scoped.field_failures
    assert (2, "ds_no") in scoped.field_failures
    assert (3, "ds_no") in scoped.field_failures
    assert (3, "date") in scoped.field_failures
    assert (4, "date") in scoped.field_failures
    assert (2, "date") in scoped.field_failures
    assert "could not verify: date unreadable" in " ".join(
        result.reason for result in scoped.for_field(2, "date")
    )


def test_duplicate_ds_flags_both_implicated_cells() -> None:
    scoped = scope_sheet([row(ds_no="1"), row(ds_no="1")])

    for number in (1, 2):
        assert "duplicate DS.No 1" in " ".join(
            result.reason for result in scoped.for_field(number, "ds_no")
        )


def test_decreasing_date_flags_both_implicated_cells() -> None:
    scoped = scope_sheet([
        row(date="2026-08-02"),
        row(ds_no="2", date="2026-08-01"),
    ])

    for number in (1, 2):
        assert "earlier than" in " ".join(
            result.reason for result in scoped.for_field(number, "date")
        )


def test_merged_km_and_route_text_in_toll_are_not_accepted_as_numbers() -> None:
    scoped = scope_sheet([row(closing_km="172807 137")], [{"toll": "Airport to hotel"}])
    assert (1, "close_km") in scoped.field_failures
    assert "could not verify: close_km unreadable" in " ".join(reasons(scoped, "total_km"))
    assert (1, "toll") in scoped.field_failures
