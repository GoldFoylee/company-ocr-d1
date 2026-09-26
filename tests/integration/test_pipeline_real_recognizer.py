"""Confirm the pipeline's own logic is unchanged when a real recognizer replaces the mock.

Not part of the standard suite -- like tests/integration/test_paddleocr_baseline.py, this
loads the real PP-OCRv6 model and runs it against all 5 real golden fixtures, which takes
minutes, not seconds. Run it explicitly:

    OCR_BASELINE=1 pytest tests/integration/test_pipeline_real_recognizer.py -s -m manual

Unlike test_paddleocr_baseline.py (which scores raw OCR accuracy against ground truth),
this test exercises run_sheet_pipeline end to end -- grid detection, cropping, recognition,
validation, flagging, and persistence -- and asserts only structural invariants that must
hold regardless of which recognizer produced the text: row/extraction counts, grid
dimensions, crop files on disk, confidence within [0.0, 1.0], and audit fields. It never
asserts specific OCR text, since PP-OCRv6's real output is not the deterministic
"MOCK_TEXT" tests/integration/test_pipeline.py's mock-backed tests rely on.

Writes go through the same rollback-savepoint db_session fixture as test_pipeline.py, so
this never leaves rows in the shared dev database -- see scripts/run_real_pipeline.py for
the real, persisted run against these same fixtures.
"""

import json
import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import cv2
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Extraction, Sheet
from app.ocr.paddle import PaddleOCRRecognizer
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


def _ocr_baseline_enabled() -> bool:
    return os.environ.get("OCR_BASELINE") == "1"


pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        not _ocr_baseline_enabled(),
        reason="set OCR_BASELINE=1 to run the real PP-OCRv6 pipeline (slow; downloads model "
        "weights on first use)",
    ),
]


@pytest.fixture(scope="module")
def real_recognizer() -> PaddleOCRRecognizer:
    """Build one real recognizer for the whole module -- model load is the expensive part."""
    return PaddleOCRRecognizer()


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
def test_real_recognizer_does_not_change_pipeline_structure(
    fixture_id: str,
    real_recognizer: PaddleOCRRecognizer,
    db_session: Session,
    tmp_path: Path,
) -> None:
    fixture_path = FIXTURE_DIRECTORY / f"{fixture_id}.jpg"
    ground_truth = json.loads((FIXTURE_DIRECTORY / f"{fixture_id}.json").read_text())
    expected_rows = len(ground_truth["rows"])

    result = run_sheet_pipeline(
        image_path=fixture_path,
        crop_root=tmp_path / "crops",
        db=db_session,
        recognizer=real_recognizer,
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
    assert stored_sheet.status in ("pending", "review")

    extractions = db_session.scalars(
        select(Extraction).where(Extraction.sheet_id == result.sheet_id).order_by(Extraction.id)
    ).all()
    assert len(extractions) == expected_rows * len(STORED_FIELDS)
    assert result.row_count == expected_rows
    assert result.extraction_count == len(extractions)
    assert len(result.grid_lines.column_boundaries) == 13
    assert len(result.grid_lines.row_boundaries) == 16
    assert result.roster_match is not None
    assert result.roster_match.canonical_name == "Morgan Alder"
    assert len(result.validation_results) == expected_rows * 2 + 2
    assert {extraction.field_name for extraction in extractions} == STORED_FIELDS

    for extraction in extractions:
        crop_path = Path(extraction.image_crop_ref)
        assert crop_path.is_file()
        assert crop_path.name.startswith(f"row{extraction.row_number:02d}_")
        assert crop_path.name.endswith(f"_{extraction.field_name}.jpg")
        assert cv2.imread(extraction.image_crop_ref) is not None
        assert isinstance(extraction.raw_ocr_value, str)
        assert 0.0 <= extraction.confidence <= 1.0
        assert isinstance(extraction.rule_flag, bool)
        if extraction.rule_flag:
            assert extraction.rule_flag_reason
        else:
            assert extraction.rule_flag_reason is None
        assert extraction.final_value is None  # No human correction has occurred.
        assert extraction.reviewer_id is None
        assert extraction.created_at is not None
        assert extraction.reviewed_at is None

    assert not list((tmp_path / "crops").rglob("*guest_name*"))
    assert not any("guest_name" in extraction.field_name for extraction in extractions)
