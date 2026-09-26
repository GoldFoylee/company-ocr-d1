"""Integration tests for sheet-oriented review data and crop delivery."""

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.cropping.cells import FIELD_NAMES
from app.database import get_db
from app.main import app
from app.models import Extraction, Sheet
from app.routers.sheets import get_crop_root


@pytest.fixture
def db_session() -> Iterator[Session]:
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


@pytest.fixture
def crop_root(tmp_path: Path) -> Path:
    return tmp_path / "crops"


@pytest.fixture
def client(db_session: Session, crop_root: Path) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_crop_root] = lambda: crop_root
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def seed_sheet(
    db: Session,
    *,
    vehicle: str = "FAKE-001",
    branch: str = "Test branch",
    sheet_date: date = date(2026, 9, 26),
    status: str = "review",
) -> Sheet:
    sheet = Sheet(
        vehicle=vehicle,
        branch=branch,
        date=sheet_date,
        image_path="/data/uploads/sheet.jpg",
        status=status,
    )
    db.add(sheet)
    db.flush()
    return sheet


def seed_extraction(
    db: Session,
    sheet: Sheet,
    *,
    row_number: int,
    field_name: str,
    crop_path: Path,
    raw_value: str,
    final_value: str | None = None,
    confidence: float | None = 0.97,
    rule_flag: bool = False,
    reason: str | None = None,
    reviewed_at: datetime | None = None,
) -> Extraction:
    extraction = Extraction(
        sheet_id=sheet.id,
        row_number=row_number,
        field_name=field_name,
        image_crop_ref=str(crop_path),
        raw_ocr_value=raw_value,
        final_value=final_value,
        confidence=confidence,
        rule_flag=rule_flag,
        rule_flag_reason=reason,
        reviewed_at=reviewed_at,
    )
    db.add(extraction)
    db.flush()
    return extraction


def test_list_sheets_returns_all_sheets_newest_first(
    client: TestClient, db_session: Session
) -> None:
    older = seed_sheet(db_session, vehicle="FAKE-OLD", status="verified")
    newer = seed_sheet(db_session, vehicle="FAKE-NEW", status="review")

    response = client.get("/sheets")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [newer.id, older.id]
    assert response.json()[0] == {
        "id": newer.id,
        "vehicle": "FAKE-NEW",
        "branch": "Test branch",
        "date": "2026-09-26",
        "status": "review",
        "force_verified": False,
    }


def test_sheet_detail_groups_rows_in_physical_column_order_and_uses_effective_value(
    client: TestClient,
    db_session: Session,
    crop_root: Path,
) -> None:
    sheet = seed_sheet(db_session)
    row_two = seed_extraction(
        db_session,
        sheet,
        row_number=2,
        field_name="date",
        crop_path=crop_root / "row-2-date.jpg",
        raw_value="26/09/2026",
    )
    flagged = seed_extraction(
        db_session,
        sheet,
        row_number=1,
        field_name="start_km",
        crop_path=crop_root / "row-1-start-km.jpg",
        raw_value="1O00",
        final_value="1000",
        confidence=0.55,
        rule_flag=True,
        reason="Numeric field contains a letter",
        reviewed_at=datetime.now(UTC),
    )
    clean = seed_extraction(
        db_session,
        sheet,
        row_number=1,
        field_name="ds_no",
        crop_path=crop_root / "row-1-ds.jpg",
        raw_value="1",
    )

    response = client.get(f"/sheets/{sheet.id}")

    assert response.status_code == 200
    body = response.json()
    assert [column["name"] for column in body["columns"]] == list(FIELD_NAMES)
    assert [row["row_number"] for row in body["rows"]] == [1, 2]

    row_one_cells = body["rows"][0]["cells"]
    assert [cell["field_name"] for cell in row_one_cells] == list(FIELD_NAMES)
    by_name = {cell["field_name"]: cell for cell in row_one_cells}
    assert by_name["ds_no"]["id"] == clean.id
    assert by_name["ds_no"]["effective_value"] == "1"
    assert by_name["ds_no"]["needs_review"] is False
    assert by_name["start_km"]["id"] == flagged.id
    assert by_name["start_km"]["raw_ocr_value"] == "1O00"
    assert by_name["start_km"]["final_value"] == "1000"
    assert by_name["start_km"]["effective_value"] == "1000"
    assert by_name["start_km"]["needs_review"] is False
    assert by_name["start_km"]["crop_url"] == f"/review/crops/{flagged.id}"
    assert by_name["date"]["missing"] is True

    row_two_cells = {cell["field_name"]: cell for cell in body["rows"][1]["cells"]}
    assert row_two_cells["date"]["id"] == row_two.id


def test_unresolved_flag_is_the_only_cell_state_that_needs_review(
    client: TestClient, db_session: Session, crop_root: Path
) -> None:
    sheet = seed_sheet(db_session)
    extraction = seed_extraction(
        db_session,
        sheet,
        row_number=1,
        field_name="close_km",
        crop_path=crop_root / "flagged.jpg",
        raw_value="9999",
        rule_flag=True,
        reason="Needs confirmation",
    )

    response = client.get(f"/sheets/{sheet.id}")

    cell = next(
        item
        for item in response.json()["rows"][0]["cells"]
        if item["field_name"] == "close_km"
    )
    assert cell["id"] == extraction.id
    assert cell["needs_review"] is True
    assert cell["rule_flag_reason"] == "Needs confirmation"


def test_guest_name_is_always_a_synthetic_excluded_placeholder_and_never_leaks(
    client: TestClient, db_session: Session, crop_root: Path
) -> None:
    sheet = seed_sheet(db_session)
    seed_extraction(
        db_session,
        sheet,
        row_number=1,
        field_name="date",
        crop_path=crop_root / "date.jpg",
        raw_value="26/09/2026",
    )
    rogue = seed_extraction(
        db_session,
        sheet,
        row_number=1,
        field_name="guest_name",
        crop_path=crop_root / "guest.jpg",
        raw_value="SENSITIVE GUEST CONTENT",
        final_value="SENSITIVE CORRECTION",
        rule_flag=True,
        reason="SENSITIVE REASON",
    )

    response = client.get(f"/sheets/{sheet.id}")

    assert response.status_code == 200
    assert "SENSITIVE" not in response.text
    guest = next(
        item
        for item in response.json()["rows"][0]["cells"]
        if item["field_name"] == "guest_name"
    )
    assert guest == {
        "id": None,
        "row_number": 1,
        "field_name": "guest_name",
        "raw_ocr_value": None,
        "final_value": None,
        "effective_value": None,
        "confidence": None,
        "rule_flag": False,
        "rule_flag_reason": None,
        "reviewed_at": None,
        "needs_review": False,
        "crop_url": None,
        "excluded": True,
        "missing": False,
    }
    assert client.get(f"/review/crops/{rogue.id}").status_code == 404
    assert client.post(
        f"/review/fields/{rogue.id}/correction", json={"final_value": "still secret"}
    ).status_code == 404
    assert client.get(f"/review/queue?sheet_id={sheet.id}").json() == []
    verification = client.post(f"/review/sheets/{sheet.id}/verify")
    assert verification.status_code == 200
    assert verification.json()["unreviewed_flagged_count"] == 0


def test_crop_endpoint_serves_non_guest_image_bytes(
    client: TestClient, db_session: Session, crop_root: Path
) -> None:
    crop_root.mkdir()
    crop = crop_root / "cell.png"
    crop.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    sheet = seed_sheet(db_session)
    extraction = seed_extraction(
        db_session,
        sheet,
        row_number=1,
        field_name="date",
        crop_path=crop,
        raw_value="26/09/2026",
    )

    response = client.get(f"/review/crops/{extraction.id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == crop.read_bytes()


@pytest.mark.parametrize("case", ["missing", "outside", "unknown-type"])
def test_crop_endpoint_returns_404_for_unservable_paths(
    case: str,
    client: TestClient,
    db_session: Session,
    crop_root: Path,
    tmp_path: Path,
) -> None:
    crop_root.mkdir()
    if case == "missing":
        crop = crop_root / "missing.jpg"
    elif case == "outside":
        crop = tmp_path / "outside.jpg"
        crop.write_bytes(b"private")
    else:
        crop = crop_root / "cell.txt"
        crop.write_bytes(b"not an image")
    sheet = seed_sheet(db_session)
    extraction = seed_extraction(
        db_session,
        sheet,
        row_number=1,
        field_name="date",
        crop_path=crop,
        raw_value="26/09/2026",
    )

    response = client.get(f"/review/crops/{extraction.id}")

    assert response.status_code == 404


def test_sheet_detail_returns_404_for_unknown_sheet(client: TestClient) -> None:
    assert client.get("/sheets/999999").status_code == 404
