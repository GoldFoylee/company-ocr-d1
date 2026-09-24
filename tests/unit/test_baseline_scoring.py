"""Unit tests for the baseline measurement's scoring and report rendering.

No OCR model runs here -- every record is built from known text, not from a
prediction. This is what actually runs in CI; the manual baseline test only
supplies real OCR output to these same functions.
"""

import json

import pytest

from tests.support.baseline_report import RunMetadata, render_json_records, render_markdown_report
from tests.support.baseline_scoring import (
    ScoredCrop,
    bucket_counts,
    bucket_for,
    build_scored_crop,
    canonical_exact,
    canonicalize,
    char_similarity,
    no_ground_truth_records,
    raw_exact,
    summarize_field,
)

# --- bucket_for ----------------------------------------------------------


def test_guest_name_is_always_redacted_regardless_of_ground_truth() -> None:
    assert bucket_for("guest_name", None) == "redacted"
    assert bucket_for("guest_name", "Someone") == "redacted"


@pytest.mark.parametrize("missing_value", [None, ""])
def test_missing_ground_truth_is_no_ground_truth(missing_value) -> None:
    assert bucket_for("journey_details", missing_value) == "no_ground_truth"


def test_zero_ground_truth_is_scored_not_missing() -> None:
    # 0 is a real, present value for toll/parking -- not "missing".
    assert bucket_for("toll", 0) == "scored"


def test_present_value_is_scored() -> None:
    assert bucket_for("date", "2026-08-01") == "scored"


# --- canonicalize: date ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-08-01", "2026-08-01"),
        ("1/8/26", "2026-08-01"),
        ("01/08/2026", "2026-08-01"),
        ("1-8-26", "2026-08-01"),
        ("1|8|26", "2026-08-01"),
        ("  1|8|26  ", "2026-08-01"),
    ],
)
def test_canonical_date_parses_known_formats(raw: str, expected: str) -> None:
    assert canonicalize("date", raw) == expected


def test_canonical_date_returns_none_for_unparseable_text() -> None:
    assert canonicalize("date", "not a date") is None


# --- canonicalize: time -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("08:00", "08:00"),
        ("8:00 AM", "08:00"),
        ("8:00AM", "08:00"),
        ("8:00 am", "08:00"),
        ("8:00 PM", "20:00"),
    ],
)
def test_canonical_time_parses_known_formats(raw: str, expected: str) -> None:
    assert canonicalize("start_time", raw) == expected
    assert canonicalize("close_time", raw) == expected


def test_canonical_time_returns_none_for_unparseable_text() -> None:
    assert canonicalize("start_time", "sometime") is None


# --- canonicalize: km --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("23695", "23695"),
        ("23,695", "23695"),
        ("23 695", "23695"),
        ("023695", "23695"),
    ],
)
def test_canonical_km_strips_separators(raw: str, expected: str) -> None:
    assert canonicalize("start_km", raw) == expected
    assert canonicalize("close_km", raw) == expected
    assert canonicalize("total_km", raw) == expected


def test_canonical_km_returns_none_when_no_digits() -> None:
    assert canonicalize("start_km", "unreadable") is None


# --- canonicalize: total_time ------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12h", "12H"),
        ("12", "12H"),
        ("0h", "0H"),
        ("0", "0H"),
        ("1d", "1D"),
        ("day", "1D"),
        ("1 day", "1D"),
    ],
)
def test_canonical_total_time_maps_known_aliases(raw: str, expected: str) -> None:
    assert canonicalize("total_time", raw) == expected


def test_canonical_total_time_returns_none_for_unknown_value() -> None:
    assert canonicalize("total_time", "3h") is None


# --- canonicalize: toll / parking -------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", "0"),
        ("", "0"),
        ("   ", "0"),
        ("50", "50"),
        ("Rs. 50", "50"),
    ],
)
def test_canonical_toll_and_parking_blank_means_zero(raw: str, expected: str) -> None:
    assert canonicalize("toll", raw) == expected
    assert canonicalize("parking", raw) == expected


# --- canonicalize: default (e.g. journey_details) ---------------------------


def test_default_canonicalization_normalizes_whitespace_and_case() -> None:
    assert canonicalize("journey_details", "  gh+299 +316\t+ps s+gh  ") == "GH+299 +316 +PS S+GH"


# --- metrics -----------------------------------------------------------------


def test_raw_exact_is_verbatim_no_transformation() -> None:
    assert raw_exact("23695", "23695") is True
    assert raw_exact(" 23695", "23695") is False
    assert raw_exact("23695", "23,695") is False


def test_canonical_exact_true_when_canonical_forms_match() -> None:
    assert canonical_exact("start_km", "23,695", "23695") is True


def test_canonical_exact_false_when_either_side_unparseable() -> None:
    assert canonical_exact("date", "not a date", "2026-08-01") is False
    assert canonical_exact("date", "1|8|26", "not a date") is False


def test_char_similarity_is_one_for_identical_strings() -> None:
    assert char_similarity("GH+299+316", "GH+299+316") == 1.0


def test_char_similarity_is_zero_for_completely_different_strings_of_equal_length() -> None:
    assert char_similarity("aaaa", "bbbb") == 0.0


def test_char_similarity_is_between_zero_and_one_for_a_near_miss() -> None:
    similarity = char_similarity("GH+299", "GH+298")
    assert 0.0 < similarity < 1.0


# --- build_scored_crop -------------------------------------------------------


def test_build_scored_crop_scores_a_present_field() -> None:
    record = build_scored_crop(
        sheet_id="sheet_001",
        row=0,
        field_name="start_km",
        ground_truth_value=23695,
        ocr_text="23695",
        confidence=0.93,
        elapsed_ms=12.5,
    )

    assert record.bucket == "scored"
    assert record.ground_truth == "23695"
    assert record.raw_exact is True
    assert record.canonical_exact is True
    assert record.char_similarity == 1.0
    assert record.confidence == 0.93


def test_build_scored_crop_redacted_field_has_no_metrics() -> None:
    record = build_scored_crop(
        sheet_id="sheet_001",
        row=0,
        field_name="guest_name",
        ground_truth_value=None,
        ocr_text=None,
        confidence=None,
        elapsed_ms=None,
    )

    assert record.bucket == "redacted"
    assert record.raw_exact is None
    assert record.canonical_exact is None
    assert record.char_similarity is None


def test_build_scored_crop_no_ground_truth_still_keeps_verbatim_ocr_text() -> None:
    record = build_scored_crop(
        sheet_id="sheet_005",
        row=0,
        field_name="journey_details",
        ground_truth_value="",
        ocr_text="illegible scrawl",
        confidence=0.31,
        elapsed_ms=40.0,
    )

    assert record.bucket == "no_ground_truth"
    assert record.ocr_text == "illegible scrawl"
    assert record.confidence == 0.31
    assert record.raw_exact is None
    assert record.canonical_exact is None
    assert record.char_similarity is None


def test_build_scored_crop_zero_ground_truth_is_scored() -> None:
    record = build_scored_crop(
        sheet_id="sheet_001",
        row=0,
        field_name="toll",
        ground_truth_value=0,
        ocr_text="",
        confidence=0.5,
        elapsed_ms=5.0,
    )

    assert record.bucket == "scored"
    assert record.ground_truth == "0"
    assert record.canonical_exact is True  # blank OCR -> "0", ground truth "0" -> "0"


# --- summaries ---------------------------------------------------------------


def _make_records() -> list[ScoredCrop]:
    return [
        build_scored_crop(
            sheet_id="sheet_001",
            row=0,
            field_name="start_km",
            ground_truth_value=23695,
            ocr_text="23695",
            confidence=0.9,
            elapsed_ms=1.0,
        ),
        build_scored_crop(
            sheet_id="sheet_001",
            row=1,
            field_name="start_km",
            ground_truth_value=23796,
            ocr_text="23786",  # one digit off
            confidence=0.7,
            elapsed_ms=1.0,
        ),
        build_scored_crop(
            sheet_id="sheet_001",
            row=0,
            field_name="guest_name",
            ground_truth_value=None,
            ocr_text=None,
            confidence=None,
            elapsed_ms=None,
        ),
        build_scored_crop(
            sheet_id="sheet_005",
            row=0,
            field_name="journey_details",
            ground_truth_value="",
            ocr_text="something",
            confidence=0.2,
            elapsed_ms=2.0,
        ),
    ]


def test_summarize_field_aggregates_only_scored_records_for_that_field() -> None:
    summary = summarize_field("start_km", _make_records())

    assert summary.scored_count == 2
    assert summary.raw_exact_count == 1
    assert summary.canonical_exact_count == 1
    assert 0.0 < summary.mean_char_similarity < 1.0
    assert summary.raw_exact_rate == 0.5


def test_summarize_field_with_no_scored_records_is_all_zero() -> None:
    summary = summarize_field("guest_name", _make_records())

    assert summary.scored_count == 0
    assert summary.raw_exact_rate == 0.0
    assert summary.canonical_exact_rate == 0.0


def test_bucket_counts_reconciles_to_total_records() -> None:
    records = _make_records()

    counts = bucket_counts(records)

    assert sum(counts.values()) == len(records)
    assert counts["scored"] == 2
    assert counts["redacted"] == 1
    assert counts["no_ground_truth"] == 1


def test_no_ground_truth_records_returns_only_that_bucket_with_verbatim_text() -> None:
    entries = no_ground_truth_records(_make_records())

    assert len(entries) == 1
    assert entries[0].sheet_id == "sheet_005"
    assert entries[0].field_name == "journey_details"
    assert entries[0].ocr_text == "something"


# --- toll / parking sharing one physical crop --------------------------------


def test_toll_and_parking_are_scored_independently_from_the_same_ocr_result() -> None:
    # app/cropping/cells.py tags one physical "Toll Parking" crop with both
    # logical field names -- the harness calls recognize() once and builds one
    # record per tag from that single (text, confidence) result.
    shared_text, shared_confidence = "50", 0.8

    toll_record = build_scored_crop(
        sheet_id="sheet_001",
        row=0,
        field_name="toll",
        ground_truth_value=50,
        ocr_text=shared_text,
        confidence=shared_confidence,
        elapsed_ms=3.0,
    )
    parking_record = build_scored_crop(
        sheet_id="sheet_001",
        row=0,
        field_name="parking",
        ground_truth_value=0,
        ocr_text=shared_text,
        confidence=shared_confidence,
        elapsed_ms=3.0,
    )

    assert toll_record.raw_exact is True
    assert parking_record.raw_exact is False
    assert parking_record.canonical_exact is False


# --- report rendering ---------------------------------------------------------


def test_render_markdown_report_includes_required_sections() -> None:
    metadata = RunMetadata(
        model_tier="medium",
        paddleocr_version="3.7.0",
        paddlepaddle_version="3.3.1",
        device="cpu",
        total_wall_clock_seconds=123.4,
    )

    report = render_markdown_report(_make_records(), metadata)

    assert "measurement, not a pass/fail gate" in report
    assert "Canonicalization rules" in report
    assert "No usable ground truth" in report
    assert "sheet_005" in report
    assert "something" in report  # verbatim OCR text on the illegible row
    assert "Run environment" in report
    assert "3.7.0" in report
    assert "Per-sheet breakdown" in report


def test_render_json_records_round_trips_through_json() -> None:
    records = _make_records()

    payload = json.loads(render_json_records(records))

    assert len(payload) == len(records)
    assert {entry["bucket"] for entry in payload} == {"scored", "redacted", "no_ground_truth"}
    # No real guest name ever appears -- redacted records carry no ocr_text.
    redacted = next(entry for entry in payload if entry["bucket"] == "redacted")
    assert redacted["ocr_text"] is None
