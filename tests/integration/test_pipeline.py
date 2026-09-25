"""End-to-end pipeline tests against the anonymized scanned sheets."""

import json
import os
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import cv2
import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Extraction, Sheet
from app.ocr.mock import MockRecognizer
from app.pipeline import run_sheet_pipeline

FIXTURE_DIRECTORY = Path("tests/fixtures/anonymized")
FIXTURE_IDS = tuple(f"sheet_{number:03d}" for number in range(1, 6))
STORED_FIELDS = {
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
VALIDATED_FIELDS = {
    "date",
    "start_km",
    "close_km",
    "total_km",
    "start_time",
    "close_time",
    "total_time",
}


class CountingMockRecognizer(MockRecognizer):
    def __init__(self, text: str, confidence: float) -> None:
        super().__init__(text=text, confidence=confidence)
        self.calls = 0

    def recognize(
        self, cell_image: np.ndarray, *, field_name: str | None = None
    ) -> tuple[str, float]:
        self.calls += 1
        return super().recognize(cell_image, field_name=field_name)


class FixtureDsMockRecognizer(MockRecognizer):
    """Return fixture DS numbers for their actual crop calls; other text stays canned."""

    def __init__(self, ds_numbers: list[str], confidence: float = 0.9) -> None:
        super().__init__(text="MOCK_TEXT", confidence=confidence)
        self.ds_numbers = ds_numbers
        self.calls = 0

    def recognize(
        self, cell_image: np.ndarray, *, field_name: str | None = None
    ) -> tuple[str, float]:
        text, confidence = super().recognize(cell_image, field_name=field_name)
        call_index = self.calls
        self.calls += 1
        if call_index % len(STORED_FIELDS) == 0:
            return self.ds_numbers[call_index // len(STORED_FIELDS)], confidence
        return text, confidence


@pytest.fixture
def db_session() -> Iterator[Session]:
    """Keep committed pipeline writes isolated from the rest of the test database."""
    engine = create_engine(os.environ["DATABASE_URL"])
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_real_sheet_pipeline_persists_every_extraction_and_audit_field(
    fixture_id: str, db_session: Session, tmp_path: Path
) -> None:
    fixture_path = FIXTURE_DIRECTORY / f"{fixture_id}.jpg"
    ground_truth = json.loads((FIXTURE_DIRECTORY / f"{fixture_id}.json").read_text())
    expected_rows = len(ground_truth["rows"])
    ds_numbers = [str(row["ds_no"]) for row in ground_truth["rows"]]
    recognizer = FixtureDsMockRecognizer(ds_numbers)

    result = run_sheet_pipeline(
        image_path=fixture_path,
        crop_root=tmp_path / "crops",
        db=db_session,
        recognizer=recognizer,
        vehicle="SYNTHETIC-VEHICLE",
        branch="Synthetic Branch",
        sheet_date=date(2026, 9, 24),
        roster_query="Morgon Alder",
        roster_names=("Morgan Alder", "Jules Whitaker", "Ravi Calder"),
    )

    stored_sheet = db_session.get(Sheet, result.sheet_id)
    assert stored_sheet is not None
    assert stored_sheet.vehicle == "SYNTHETIC-VEHICLE"
    assert stored_sheet.branch == "Synthetic Branch"
    assert stored_sheet.date == date(2026, 9, 24)
    assert stored_sheet.image_path == str(fixture_path.resolve())
    assert stored_sheet.status == "review"

    extractions = db_session.scalars(
        select(Extraction)
        .where(Extraction.sheet_id == result.sheet_id)
        .order_by(Extraction.id)
    ).all()
    assert len(extractions) == expected_rows * len(STORED_FIELDS)
    assert result.row_count == expected_rows
    assert result.extraction_count == len(extractions)
    assert len(result.grid_lines.column_boundaries) == 13
    assert len(result.grid_lines.row_boundaries) == 16
    assert result.roster_match is not None
    assert result.roster_match.canonical_name == "Morgan Alder"
    assert len(result.validation_results) == expected_rows * 2 + 2
    assert recognizer.calls == len(extractions)
    assert next(item for item in result.validation_results if item.rule == "unique_ds_no").passed
    assert {extraction.field_name for extraction in extractions} == STORED_FIELDS

    rows_seen: dict[int, set[str]] = {}
    for extraction in extractions:
        crop_path = Path(extraction.image_crop_ref)
        assert crop_path.is_file()
        assert crop_path.name.endswith(f"_{extraction.field_name}.jpg")
        row_match = re.fullmatch(r"row(\d{2})_.+\.jpg", crop_path.name)
        assert row_match is not None
        row_number = int(row_match.group(1))
        rows_seen.setdefault(row_number, set()).add(extraction.field_name)
        assert cv2.imread(extraction.image_crop_ref) is not None
        if extraction.field_name == "ds_no":
            assert extraction.raw_ocr_value == ds_numbers[row_number - 1]
        else:
            assert extraction.raw_ocr_value == "MOCK_TEXT"
        assert extraction.confidence == pytest.approx(0.9)
        assert isinstance(extraction.rule_flag, bool)
        if extraction.rule_flag:
            assert extraction.rule_flag_reason
        else:
            assert extraction.rule_flag_reason is None
        assert extraction.rule_flag is (extraction.field_name in VALIDATED_FIELDS)
        assert extraction.final_value is None  # No human correction has occurred.
        assert extraction.reviewer_id is None
        assert extraction.created_at is not None
        assert extraction.reviewed_at is None

    assert rows_seen == {row: STORED_FIELDS for row in range(1, expected_rows + 1)}
    assert not list((tmp_path / "crops").rglob("*guest_name*"))
    assert not any("guest_name" in extraction.field_name for extraction in extractions)


def test_mocked_values_fail_validation_and_enter_review_queue(
    db_session: Session, tmp_path: Path
) -> None:
    recognizer = CountingMockRecognizer(text="MOCK_TEXT", confidence=0.5)
    result = run_sheet_pipeline(
        image_path=FIXTURE_DIRECTORY / "sheet_004.jpg",
        crop_root=tmp_path / "crops",
        db=db_session,
        recognizer=recognizer,
        vehicle="SYNTHETIC-VEHICLE",
        branch="Synthetic Branch",
        sheet_date=date(2026, 9, 24),
        roster_query="Jules Whittaker",
        roster_names=("Morgan Alder", "Jules Whitaker"),
    )
    assert result.row_count == 11
    assert result.roster_match is not None
    assert result.roster_match.canonical_name == "Jules Whitaker"
    assert any(not item.passed for item in result.validation_results)

    extractions = db_session.scalars(
        select(Extraction).where(Extraction.sheet_id == result.sheet_id)
    ).all()
    assert len(extractions) == 121
    assert recognizer.calls == len(extractions)
    assert all(item.rule_flag for item in extractions)
    assert all("Low OCR confidence" in (item.rule_flag_reason or "") for item in extractions)
    assert all(
        "Validation failed" in (item.rule_flag_reason or "")
        for item in extractions
        if item.field_name in VALIDATED_FIELDS
    )


def test_duplicate_ds_number_from_real_fixture_crop_fails_uniqueness(
    db_session: Session, tmp_path: Path
) -> None:
    fixture_id = "sheet_004"
    ground_truth = json.loads((FIXTURE_DIRECTORY / f"{fixture_id}.json").read_text())
    ds_numbers = [str(row["ds_no"]) for row in ground_truth["rows"]]
    ds_numbers[1] = ds_numbers[0]

    result = run_sheet_pipeline(
        image_path=FIXTURE_DIRECTORY / f"{fixture_id}.jpg",
        crop_root=tmp_path / "crops",
        db=db_session,
        recognizer=FixtureDsMockRecognizer(ds_numbers),
        vehicle="SYNTHETIC-VEHICLE",
        branch="Synthetic Branch",
        sheet_date=date(2026, 9, 24),
        roster_query="Morgon Alder",
        roster_names=("Morgan Alder",),
    )

    uniqueness = next(item for item in result.validation_results if item.rule == "unique_ds_no")
    assert not uniqueness.passed
    assert "duplicate DS.No 1 found at rows 1 and 2" in uniqueness.reason
    ds_extractions = db_session.scalars(
        select(Extraction).where(
            Extraction.sheet_id == result.sheet_id,
            Extraction.field_name == "ds_no",
        )
    ).all()
    assert len(ds_extractions) == 11
    assert [item.raw_ocr_value for item in ds_extractions] == ds_numbers
    assert all(item.rule_flag for item in ds_extractions)
    assert all("duplicate DS.No" in (item.rule_flag_reason or "") for item in ds_extractions)
