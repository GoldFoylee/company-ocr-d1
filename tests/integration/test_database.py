import os
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Extraction, Reviewer, Sheet

EXTRACTION_BUSINESS_COLUMNS = {
    "sheet_id",
    "row_number",
    "field_name",
    "image_crop_ref",
    "raw_ocr_value",
    "confidence",
    "rule_flag",
    "rule_flag_reason",
    "final_value",
    "reviewer_id",
    "created_at",
    "reviewed_at",
}


@pytest.fixture
def db_session() -> Iterator[Session]:
    """Run each test in a transaction against the real PostgreSQL service."""
    engine = create_engine(os.environ["DATABASE_URL"])
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()


def test_all_tables_round_trip_rows(db_session: Session) -> None:
    reviewer = Reviewer(name="Integration Reviewer")
    sheet = Sheet(
        vehicle="MH-01-AB-1234",
        branch="Mumbai",
        date=date(2026, 9, 20),
        image_path="/data/uploads/sheet-001.jpg",
        status="review",
    )
    db_session.add_all([reviewer, sheet])
    db_session.flush()

    extraction = Extraction(
        sheet_id=sheet.id,
        row_number=7,
        field_name="odometer",
        image_crop_ref="/data/crops/sheet-001-odometer.jpg",
        raw_ocr_value="12345",
        confidence=0.94,
        rule_flag=True,
        rule_flag_reason="Manual verification requested",
        final_value="12345",
        reviewer_id=reviewer.id,
    )
    db_session.add(extraction)
    db_session.flush()

    reviewer_id = reviewer.id
    sheet_id = sheet.id
    extraction_id = extraction.id
    db_session.expunge_all()

    stored_reviewer = db_session.get(Reviewer, reviewer_id)
    stored_sheet = db_session.get(Sheet, sheet_id)
    stored_extraction = db_session.get(Extraction, extraction_id)

    assert stored_reviewer is not None
    assert stored_reviewer.name == "Integration Reviewer"

    assert stored_sheet is not None
    assert stored_sheet.vehicle == "MH-01-AB-1234"
    assert stored_sheet.branch == "Mumbai"
    assert stored_sheet.date == date(2026, 9, 20)
    assert stored_sheet.image_path == "/data/uploads/sheet-001.jpg"
    assert stored_sheet.status == "review"

    assert stored_extraction is not None
    assert stored_extraction.sheet_id == sheet_id
    assert stored_extraction.row_number == 7
    assert stored_extraction.field_name == "odometer"
    assert stored_extraction.image_crop_ref == "/data/crops/sheet-001-odometer.jpg"
    assert stored_extraction.raw_ocr_value == "12345"
    assert stored_extraction.confidence == pytest.approx(0.94)
    assert stored_extraction.rule_flag is True
    assert stored_extraction.rule_flag_reason == "Manual verification requested"
    assert stored_extraction.final_value == "12345"
    assert stored_extraction.reviewer_id == reviewer_id
    assert stored_extraction.created_at is not None
    assert stored_extraction.reviewed_at is None


def test_extractions_business_columns_match_contract() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        database_columns = {
            column["name"] for column in inspect(engine).get_columns("extractions")
        }
    finally:
        engine.dispose()

    assert database_columns == {"id", *EXTRACTION_BUSINESS_COLUMNS}


def test_extraction_rejects_unknown_sheet(db_session: Session) -> None:
    extraction = Extraction(
        sheet_id=-1,
        field_name="odometer",
        image_crop_ref="/data/crops/missing-sheet.jpg",
        raw_ocr_value="12345",
    )
    db_session.add(extraction)

    with pytest.raises(IntegrityError, match="ForeignKeyViolation"):
        db_session.flush()


def test_extraction_rejects_non_positive_row_number(db_session: Session) -> None:
    sheet = Sheet(
        vehicle="MH-01-AB-1234",
        branch="Mumbai",
        date=date(2026, 9, 20),
        image_path="/data/uploads/invalid-row-number.jpg",
    )
    db_session.add(sheet)
    db_session.flush()
    db_session.add(
        Extraction(
            sheet_id=sheet.id,
            row_number=0,
            field_name="odometer",
            image_crop_ref="/data/crops/invalid-row-number.jpg",
            raw_ocr_value="12345",
        )
    )

    with pytest.raises(IntegrityError, match="CheckViolation"):
        db_session.flush()


@pytest.mark.parametrize("required_field", ["image_crop_ref", "raw_ocr_value"])
def test_extraction_rejects_null_ocr_source_fields(
    db_session: Session, required_field: str
) -> None:
    sheet = Sheet(
        vehicle="MH-01-AB-1234",
        branch="Mumbai",
        date=date(2026, 9, 20),
        image_path="/data/uploads/required-fields.jpg",
    )
    db_session.add(sheet)
    db_session.flush()

    values = {
        "sheet_id": sheet.id,
        "field_name": "odometer",
        "image_crop_ref": "/data/crops/required-fields.jpg",
        "raw_ocr_value": "12345",
    }
    values[required_field] = None
    db_session.add(Extraction(**values))

    with pytest.raises(IntegrityError, match="NotNullViolation"):
        db_session.flush()


def test_extraction_reviewed_at_can_be_set_after_creation(db_session: Session) -> None:
    sheet = Sheet(
        vehicle="MH-01-AB-1234",
        branch="Mumbai",
        date=date(2026, 9, 20),
        image_path="/data/uploads/review-timestamp.jpg",
    )
    db_session.add(sheet)
    db_session.flush()

    extraction = Extraction(
        sheet_id=sheet.id,
        field_name="odometer",
        image_crop_ref="/data/crops/review-timestamp.jpg",
        raw_ocr_value="12345",
    )
    db_session.add(extraction)
    db_session.flush()
    assert extraction.created_at is not None
    assert extraction.reviewed_at is None

    reviewed_at = datetime(2026, 9, 20, 12, 30, tzinfo=UTC)
    extraction.reviewed_at = reviewed_at
    db_session.flush()
    db_session.refresh(extraction)

    assert extraction.reviewed_at == reviewed_at


def test_sheet_rejects_missing_required_vehicle(db_session: Session) -> None:
    sheet = Sheet(
        branch="Mumbai",
        date=date(2026, 9, 20),
        image_path="/data/uploads/missing-vehicle.jpg",
    )
    db_session.add(sheet)

    with pytest.raises(IntegrityError, match="NotNullViolation"):
        db_session.flush()
