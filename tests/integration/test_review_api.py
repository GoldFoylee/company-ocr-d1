import logging
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app
from app.models import Extraction, Reviewer, Sheet


@pytest.fixture
def db_session() -> Iterator[Session]:
    """Run each test in an isolated transaction using savepoints against PostgreSQL."""
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
def client(db_session: Session) -> Iterator[TestClient]:
    """FastAPI TestClient with get_db overridden to use the transactional test session."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def seed_sheet(
    db: Session,
    vehicle: str = "MH-02-CD-5678",
    branch: str = "Pune",
    sheet_date: date | None = None,
    image_path: str = "/data/uploads/sheet-test.jpg",
    status: str = "pending",
) -> Sheet:
    sheet = Sheet(
        vehicle=vehicle,
        branch=branch,
        date=sheet_date or date(2026, 9, 21),
        image_path=image_path,
        status=status,
    )
    db.add(sheet)
    db.flush()
    return sheet


def seed_reviewer(db: Session, name: str = "Test Reviewer") -> Reviewer:
    reviewer = Reviewer(name=name)
    db.add(reviewer)
    db.flush()
    return reviewer


def seed_extraction(
    db: Session,
    sheet_id: int,
    field_name: str,
    raw_ocr_value: str = "12345",
    image_crop_ref: str = "/data/crops/cell.jpg",
    confidence: float | None = 0.95,
    rule_flag: bool = False,
    rule_flag_reason: str | None = None,
    final_value: str | None = None,
    reviewer_id: int | None = None,
    reviewed_at: datetime | None = None,
) -> Extraction:
    extraction = Extraction(
        sheet_id=sheet_id,
        field_name=field_name,
        image_crop_ref=image_crop_ref,
        raw_ocr_value=raw_ocr_value,
        confidence=confidence,
        rule_flag=rule_flag,
        rule_flag_reason=rule_flag_reason,
        final_value=final_value,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
    )
    db.add(extraction)
    db.flush()
    return extraction


# ==============================================================================
# 1. Tests for listing flagged fields awaiting review (GET /review/queue)
# ==============================================================================


def test_review_queue_empty_when_no_flagged_extractions(
    client: TestClient, db_session: Session
) -> None:
    sheet = seed_sheet(db_session)
    seed_extraction(db_session, sheet.id, "odometer", rule_flag=False)
    seed_extraction(db_session, sheet.id, "driver_name", rule_flag=False)

    response = client.get(f"/review/queue?sheet_id={sheet.id}")
    assert response.status_code == 200
    assert response.json() == []


def test_review_queue_returns_flagged_unreviewed_fields_with_sheet_metadata(
    client: TestClient, db_session: Session
) -> None:
    sheet = seed_sheet(
        db_session,
        vehicle="DL-01-AB-1234",
        branch="Delhi",
        sheet_date=date(2026, 9, 21),
    )
    # 1 clean, 2 flagged
    seed_extraction(db_session, sheet.id, "clean_field", rule_flag=False)
    ext1 = seed_extraction(
        db_session,
        sheet.id,
        "odometer",
        raw_ocr_value="88888",
        confidence=0.62,
        rule_flag=True,
        rule_flag_reason="Confidence below threshold",
    )
    ext2 = seed_extraction(
        db_session,
        sheet.id,
        "fuel_liters",
        raw_ocr_value="450",
        confidence=0.91,
        rule_flag=True,
        rule_flag_reason="Exceeds tank capacity",
    )

    response = client.get(f"/review/queue?sheet_id={sheet.id}")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2

    item1 = next(item for item in items if item["id"] == ext1.id)
    assert item1["sheet_id"] == sheet.id
    assert item1["field_name"] == "odometer"
    assert item1["raw_ocr_value"] == "88888"
    assert item1["confidence"] == pytest.approx(0.62)
    assert item1["rule_flag"] is True
    assert item1["rule_flag_reason"] == "Confidence below threshold"
    assert item1["final_value"] is None
    assert item1["reviewed_at"] is None
    assert item1["vehicle"] == "DL-01-AB-1234"
    assert item1["branch"] == "Delhi"
    assert item1["sheet_date"] == "2026-09-21"
    assert item1["sheet_status"] == "pending"

    item2 = next(item for item in items if item["id"] == ext2.id)
    assert item2["field_name"] == "fuel_liters"
    assert item2["rule_flag_reason"] == "Exceeds tank capacity"


def test_review_queue_excludes_already_reviewed_extractions(
    client: TestClient, db_session: Session
) -> None:
    sheet = seed_sheet(db_session)
    reviewer = seed_reviewer(db_session)

    # Flagged and already reviewed
    seed_extraction(
        db_session,
        sheet.id,
        "already_reviewed",
        rule_flag=True,
        final_value="corrected",
        reviewer_id=reviewer.id,
        reviewed_at=datetime.now(UTC),
    )
    # Flagged and awaiting review
    ext_pending = seed_extraction(
        db_session,
        sheet.id,
        "still_flagged",
        rule_flag=True,
        rule_flag_reason="Needs check",
    )

    response = client.get(f"/review/queue?sheet_id={sheet.id}")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == ext_pending.id


def test_review_queue_filters_by_sheet_id(client: TestClient, db_session: Session) -> None:
    sheet_a = seed_sheet(db_session, vehicle="VEHICLE-A")
    sheet_b = seed_sheet(db_session, vehicle="VEHICLE-B")

    ext_a = seed_extraction(db_session, sheet_a.id, "field_a", rule_flag=True)
    ext_b = seed_extraction(db_session, sheet_b.id, "field_b", rule_flag=True)

    response_a = client.get(f"/review/queue?sheet_id={sheet_a.id}")
    assert response_a.status_code == 200
    assert [i["id"] for i in response_a.json()] == [ext_a.id]

    response_b = client.get(f"/review/queue?sheet_id={sheet_b.id}")
    assert response_b.status_code == 200
    assert [i["id"] for i in response_b.json()] == [ext_b.id]


def test_review_queue_pagination(client: TestClient, db_session: Session) -> None:
    sheet = seed_sheet(db_session)
    ids = []
    for i in range(5):
        ext = seed_extraction(db_session, sheet.id, f"field_{i}", rule_flag=True)
        ids.append(ext.id)

    # First page: limit 2, offset 0
    resp1 = client.get(f"/review/queue?sheet_id={sheet.id}&limit=2&offset=0")
    assert resp1.status_code == 200
    assert [i["id"] for i in resp1.json()] == ids[0:2]

    # Second page: limit 2, offset 2
    resp2 = client.get(f"/review/queue?sheet_id={sheet.id}&limit=2&offset=2")
    assert resp2.status_code == 200
    assert [i["id"] for i in resp2.json()] == ids[2:4]

    # Third page: limit 2, offset 4
    resp3 = client.get(f"/review/queue?sheet_id={sheet.id}&limit=2&offset=4")
    assert resp3.status_code == 200
    assert [i["id"] for i in resp3.json()] == ids[4:5]


def test_review_queue_alias_endpoint(client: TestClient, db_session: Session) -> None:
    sheet = seed_sheet(db_session)
    seed_extraction(db_session, sheet.id, "odometer", rule_flag=True)

    resp_primary = client.get(f"/review/queue?sheet_id={sheet.id}")
    resp_alias = client.get(f"/review/flagged-fields?sheet_id={sheet.id}")

    assert resp_primary.status_code == 200
    assert resp_alias.status_code == 200
    assert resp_primary.json() == resp_alias.json()


# ==============================================================================
# 2. Tests for submitting field corrections (POST /review/fields/{id}/correction)
# ==============================================================================


def test_submit_correction_success_with_reviewer(client: TestClient, db_session: Session) -> None:
    sheet = seed_sheet(db_session)
    reviewer = seed_reviewer(db_session, name="Alice Verifier")
    extraction = seed_extraction(
        db_session,
        sheet.id,
        "odometer",
        raw_ocr_value="120OO",
        rule_flag=True,
        rule_flag_reason="Alphanumeric in numeric field",
    )

    payload = {
        "final_value": "12000",
        "reviewer_id": reviewer.id,
    }
    response = client.post(f"/review/fields/{extraction.id}/correction", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == extraction.id
    assert data["sheet_id"] == sheet.id
    assert data["final_value"] == "12000"
    assert data["reviewer_id"] == reviewer.id
    assert data["reviewed_at"] is not None

    # Verify that the field has left the review queue
    queue_resp = client.get(f"/review/queue?sheet_id={sheet.id}")
    assert queue_resp.status_code == 200
    assert all(item["id"] != extraction.id for item in queue_resp.json())

    # Verify directly in DB
    db_session.expire_all()
    updated = db_session.get(Extraction, extraction.id)
    assert updated is not None
    assert updated.final_value == "12000"
    assert updated.reviewer_id == reviewer.id
    assert updated.reviewed_at is not None


def test_submit_correction_without_reviewer_id(client: TestClient, db_session: Session) -> None:
    sheet = seed_sheet(db_session)
    extraction = seed_extraction(
        db_session,
        sheet.id,
        "driver_name",
        raw_ocr_value="Jhn Doe",
        rule_flag=True,
    )

    payload = {"final_value": "John Doe"}
    response = client.post(f"/review/fields/{extraction.id}/correction", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["final_value"] == "John Doe"
    assert data["reviewer_id"] is None
    assert data["reviewed_at"] is not None


def test_submit_correction_via_patch_alias_and_value_alias(
    client: TestClient, db_session: Session
) -> None:
    sheet = seed_sheet(db_session)
    extraction = seed_extraction(db_session, sheet.id, "odometer", rule_flag=True)

    # Use PATCH and "value" alias instead of "final_value"
    response = client.patch(f"/review/fields/{extraction.id}", json={"value": "77777"})
    assert response.status_code == 200
    assert response.json()["final_value"] == "77777"


def test_submit_correction_nonexistent_extraction_returns_404(
    client: TestClient, db_session: Session
) -> None:
    response = client.post("/review/fields/999999/correction", json={"final_value": "val"})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_submit_correction_nonexistent_reviewer_returns_404(
    client: TestClient, db_session: Session
) -> None:
    sheet = seed_sheet(db_session)
    extraction = seed_extraction(db_session, sheet.id, "odometer", rule_flag=True)

    response = client.post(
        f"/review/fields/{extraction.id}/correction",
        json={"final_value": "12345", "reviewer_id": 999999},
    )
    assert response.status_code == 404
    assert "Reviewer with id 999999 not found" in response.json()["detail"]


def test_submit_correction_missing_value_returns_422(
    client: TestClient, db_session: Session
) -> None:
    sheet = seed_sheet(db_session)
    extraction = seed_extraction(db_session, sheet.id, "odometer", rule_flag=True)

    response = client.post(f"/review/fields/{extraction.id}/correction", json={})
    assert response.status_code == 422


# ==============================================================================
# 3. Tests for sheet verification (POST /review/sheets/{id}/verify)
# ==============================================================================


def test_verify_sheet_success_when_all_flagged_fields_reviewed(
    client: TestClient, db_session: Session
) -> None:
    sheet = seed_sheet(db_session, status="pending")
    ext = seed_extraction(db_session, sheet.id, "odometer", rule_flag=True)

    # Correct the flagged field
    client.post(f"/review/fields/{ext.id}/correction", json={"final_value": "12345"})

    # Now verify the sheet
    response = client.post(f"/review/sheets/{sheet.id}/verify")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == sheet.id
    assert data["status"] == "verified"
    assert data["verified_via_force"] is False
    assert data["unreviewed_flagged_count"] == 0

    db_session.expire_all()
    updated_sheet = db_session.get(Sheet, sheet.id)
    assert updated_sheet is not None
    assert updated_sheet.status == "verified"


def test_verify_clean_sheet_with_no_flagged_fields(client: TestClient, db_session: Session) -> None:
    sheet = seed_sheet(db_session, status="pending")
    seed_extraction(db_session, sheet.id, "clean_1", rule_flag=False)
    seed_extraction(db_session, sheet.id, "clean_2", rule_flag=False)

    response = client.post(f"/review/sheets/{sheet.id}/verify")
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


def test_verify_sheet_fails_when_unreviewed_flagged_fields_remain(
    client: TestClient, db_session: Session
) -> None:
    sheet = seed_sheet(db_session, status="pending")
    seed_extraction(
        db_session,
        sheet.id,
        "bad_odometer",
        rule_flag=True,
        rule_flag_reason="Value missing",
    )

    response = client.post(f"/review/sheets/{sheet.id}/verify")
    assert response.status_code == 400
    assert "1 flagged field(s) awaiting review" in response.json()["detail"]

    # Verify sheet status in DB remained unchanged
    db_session.expire_all()
    stored = db_session.get(Sheet, sheet.id)
    assert stored is not None
    assert stored.status == "pending"


def test_verify_sheet_force_override_records_audit_log(
    client: TestClient,
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sheet = seed_sheet(
        db_session,
        vehicle="AUDIT-FORCE-99",
        branch="AuditBranch",
        status="pending",
    )
    reviewer = seed_reviewer(db_session, name="Supervisor Auditor")
    seed_extraction(db_session, sheet.id, "flagged_1", rule_flag=True)
    seed_extraction(db_session, sheet.id, "flagged_2", rule_flag=True)

    with caplog.at_level(logging.WARNING, logger="audit.review"):
        response = client.post(
            f"/review/sheets/{sheet.id}/verify?force=true&reviewer_id={reviewer.id}"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "verified"
    assert data["verified_via_force"] is True
    assert data["unreviewed_flagged_count"] == 2

    # Assert structured audit log was recorded
    assert any("AUDIT FORCE VERIFY" in record.message for record in caplog.records)
    audit_record = next(
        r for r in caplog.records if r.name == "audit.review" and "AUDIT FORCE VERIFY" in r.message
    )
    assert audit_record.levelno == logging.WARNING
    assert "AUDIT-FORCE-99" in audit_record.message
    assert str(reviewer.id) in audit_record.message or "Supervisor Auditor" in audit_record.message


def test_verify_sheet_force_via_body_payload(client: TestClient, db_session: Session) -> None:
    sheet = seed_sheet(db_session)
    seed_extraction(db_session, sheet.id, "unreviewed", rule_flag=True)

    response = client.post(
        f"/review/sheets/{sheet.id}/verify",
        json={"force": True},
    )
    assert response.status_code == 200
    assert response.json()["verified_via_force"] is True


def test_verify_sheet_nonexistent_sheet_returns_404(
    client: TestClient, db_session: Session
) -> None:
    response = client.post("/review/sheets/999999/verify")
    assert response.status_code == 404
    assert "Sheet with id 999999 not found" in response.json()["detail"]


def test_verify_sheet_nonexistent_reviewer_returns_404(
    client: TestClient, db_session: Session
) -> None:
    sheet = seed_sheet(db_session)
    response = client.post(f"/review/sheets/{sheet.id}/verify?reviewer_id=999999")
    assert response.status_code == 404
    assert "Reviewer with id 999999 not found" in response.json()["detail"]


def test_verify_sheet_direct_alias_route(client: TestClient, db_session: Session) -> None:
    sheet = seed_sheet(db_session, status="pending")
    seed_extraction(db_session, sheet.id, "clean", rule_flag=False)

    response = client.post(f"/sheets/{sheet.id}/verify")
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


# ==============================================================================
# 4. End-to-End Review Lifecycle Integration Test
# ==============================================================================


def test_end_to_end_review_lifecycle(client: TestClient, db_session: Session) -> None:
    """Demonstrate the full lifecycle:
    1. Seed a sheet with 1 clean and 2 flagged extractions.
    2. Queue correctly shows 2 items awaiting review for this sheet.
    3. Premature verification fails with 400.
    4. Reviewer corrects first flagged field -> 1 item left in queue.
    5. Premature verification still fails with 400.
    6. Reviewer corrects second flagged field -> 0 items left in queue.
    7. Sheet verification succeeds without force.
    8. Sheet status in database is 'verified'.
    """
    reviewer = seed_reviewer(db_session, name="Final Quality Reviewer")
    sheet = seed_sheet(
        db_session,
        vehicle="E2E-99-ZZ-0001",
        branch="Hyderabad",
        status="pending",
    )

    # 1 clean, 2 flagged
    seed_extraction(db_session, sheet.id, "date", raw_ocr_value="2026-09-21", rule_flag=False)
    ext_odo = seed_extraction(
        db_session,
        sheet.id,
        "odometer",
        raw_ocr_value="l000",
        rule_flag=True,
        rule_flag_reason="Non-digit character 'l' in odometer",
    )
    ext_driver = seed_extraction(
        db_session,
        sheet.id,
        "driver_name",
        raw_ocr_value="R. Sharma",
        rule_flag=True,
        rule_flag_reason="Low OCR confidence (0.55)",
    )

    # Step 2: Check review queue
    queue_resp = client.get(f"/review/queue?sheet_id={sheet.id}")
    assert queue_resp.status_code == 200
    queue_items = queue_resp.json()
    assert len(queue_items) == 2
    assert {i["field_name"] for i in queue_items} == {"odometer", "driver_name"}

    # Step 3: Premature verify fails
    verify_resp = client.post(f"/review/sheets/{sheet.id}/verify")
    assert verify_resp.status_code == 400
    assert "2 flagged field(s) awaiting review" in verify_resp.json()["detail"]

    # Step 4: Correct first field
    correct_odo_resp = client.post(
        f"/review/fields/{ext_odo.id}/correction",
        json={"final_value": "1000", "reviewer_id": reviewer.id},
    )
    assert correct_odo_resp.status_code == 200
    assert correct_odo_resp.json()["final_value"] == "1000"

    # Verify 1 item left in queue
    queue_resp_2 = client.get(f"/review/queue?sheet_id={sheet.id}")
    assert len(queue_resp_2.json()) == 1
    assert queue_resp_2.json()[0]["id"] == ext_driver.id

    # Step 5: Premature verify still fails
    verify_resp_2 = client.post(f"/review/sheets/{sheet.id}/verify")
    assert verify_resp_2.status_code == 400
    assert "1 flagged field(s) awaiting review" in verify_resp_2.json()["detail"]

    # Step 6: Correct second field
    correct_driver_resp = client.post(
        f"/review/fields/{ext_driver.id}/correction",
        json={"final_value": "Rahul Sharma", "reviewer_id": reviewer.id},
    )
    assert correct_driver_resp.status_code == 200
    assert correct_driver_resp.json()["final_value"] == "Rahul Sharma"

    # Verify 0 items left in queue
    queue_resp_3 = client.get(f"/review/queue?sheet_id={sheet.id}")
    assert queue_resp_3.json() == []

    # Step 7: Verify sheet succeeds
    verify_final_resp = client.post(
        f"/review/sheets/{sheet.id}/verify",
        json={"reviewer_id": reviewer.id},
    )
    assert verify_final_resp.status_code == 200
    assert verify_final_resp.json()["status"] == "verified"
    assert verify_final_resp.json()["verified_via_force"] is False

    # Step 8: Verify in database
    db_session.expire_all()
    db_sheet = db_session.get(Sheet, sheet.id)
    assert db_sheet is not None
    assert db_sheet.status == "verified"
