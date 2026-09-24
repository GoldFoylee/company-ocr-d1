"""Regression coverage for total-time categories in every golden fixture."""

import json
from pathlib import Path

from app.validation import TOTAL_TIME_CATEGORIES, ExtractedRowValues, ValidationEngine

FIXTURE_DIRECTORY = Path("tests/fixtures/anonymized")
FIXTURE_PATHS = tuple(sorted(FIXTURE_DIRECTORY.glob("sheet_*.json")))


def _fixture_rows() -> list[tuple[str, int, dict[str, object]]]:
    rows: list[tuple[str, int, dict[str, object]]] = []
    for fixture_path in FIXTURE_PATHS:
        payload = json.loads(fixture_path.read_text())
        rows.extend(
            (fixture_path.stem, row_number, row)
            for row_number, row in enumerate(payload["rows"], start=1)
        )
    return rows


def test_known_categories_match_the_complete_real_fixture_vocabulary() -> None:
    assert tuple(path.stem for path in FIXTURE_PATHS) == tuple(
        f"sheet_{number:03d}" for number in range(1, 6)
    )
    fixture_categories = {str(row["total_time"]) for _, _, row in _fixture_rows()}

    assert fixture_categories == TOTAL_TIME_CATEGORIES == {"0h", "12h", "1d"}


def test_every_real_fixture_total_time_value_passes_validation() -> None:
    engine = ValidationEngine()

    for fixture_id, row_number, row in _fixture_rows():
        extracted = ExtractedRowValues(
            ds_no="1",
            date="2026-01-01",
            starting_km="0",
            closing_km="0",
            total_km="0",
            start_time=str(row["start_time"]),
            closing_time=str(row["close_time"]),
            total_time=str(row["total_time"]),
        )

        result = engine.validate_time(extracted, row_number=row_number)

        assert result.passed, f"{fixture_id} row {row_number}: {result.reason}"
