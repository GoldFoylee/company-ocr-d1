"""Integration coverage for synchronous sheet upload and processing."""

import inspect
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app
from app.models import Extraction, Sheet
from app.ocr.mock import MockRecognizer
from app.routers.sheets import (
    get_crop_root,
    get_recognizer,
    get_upload_root,
    upload_sheet,
)

FIXTURE_DIRECTORY = Path("tests/fixtures/anonymized")


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
def storage_roots(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "uploads", tmp_path / "crops"


@pytest.fixture
def client(
    db_session: Session,
    storage_roots: tuple[Path, Path],
) -> Iterator[TestClient]:
    upload_root, crop_root = storage_roots
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_recognizer] = lambda: MockRecognizer("1", 0.99)
    app.dependency_overrides[get_upload_root] = lambda: upload_root
    app.dependency_overrides[get_crop_root] = lambda: crop_root
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_upload_endpoint_is_sync_for_fastapi_threadpool() -> None:
    assert inspect.iscoroutinefunction(upload_sheet) is False


def test_upload_runs_pipeline_and_persists_row_addressable_extractions(
    client: TestClient,
    db_session: Session,
    storage_roots: tuple[Path, Path],
) -> None:
    fixture_id = "sheet_001"
    fixture_path = FIXTURE_DIRECTORY / f"{fixture_id}.jpg"
    ground_truth = json.loads(
        (FIXTURE_DIRECTORY / f"{fixture_id}.json").read_text(encoding="utf-8")
    )

    with fixture_path.open("rb") as image:
        response = client.post(
            "/sheets/upload",
            files={"image": (fixture_path.name, image, "image/jpeg")},
            data={
                "vehicle": "FAKE-001",
                "branch": "Upload integration test",
                "sheet_date": "2026-09-25",
            },
        )

    assert response.status_code == 201
    body = response.json()
    expected_rows = len(ground_truth["rows"])
    assert body == {
        "sheet_id": body["sheet_id"],
        "row_count": expected_rows,
        "extraction_count": expected_rows * 11,
        "status": "review",
    }

    sheet = db_session.get(Sheet, body["sheet_id"])
    assert sheet is not None
    assert sheet.vehicle == "FAKE-001"
    assert sheet.branch == "Upload integration test"
    assert Path(sheet.image_path).is_file()
    assert Path(sheet.image_path).parent == storage_roots[0]
    assert Path(sheet.image_path).name != fixture_path.name

    extractions = db_session.scalars(
        select(Extraction)
        .where(Extraction.sheet_id == sheet.id)
        .order_by(Extraction.row_number, Extraction.id)
    ).all()
    assert len(extractions) == expected_rows * 11
    assert {item.row_number for item in extractions} == set(range(1, expected_rows + 1))
    for row_number in range(1, expected_rows + 1):
        row = [item for item in extractions if item.row_number == row_number]
        assert len(row) == 11
        assert "guest_name" not in {item.field_name for item in row}


def test_upload_rejects_non_image_content_type_without_writing_file(
    client: TestClient,
    storage_roots: tuple[Path, Path],
) -> None:
    response = client.post(
        "/sheets/upload",
        files={"image": ("sheet.txt", b"not an image", "text/plain")},
        data={"vehicle": "FAKE-001", "branch": "Test", "sheet_date": "2026-09-25"},
    )

    assert response.status_code == 415
    assert not storage_roots[0].exists()


def test_upload_removes_invalid_image_after_pipeline_rejects_it(
    client: TestClient,
    db_session: Session,
    storage_roots: tuple[Path, Path],
) -> None:
    response = client.post(
        "/sheets/upload",
        files={"image": ("broken.jpg", b"not an image", "image/jpeg")},
        data={"vehicle": "FAKE-001", "branch": "Test", "sheet_date": "2026-09-25"},
    )

    assert response.status_code == 422
    assert list(storage_roots[0].glob("*")) == []
    assert db_session.scalars(select(Sheet)).all() == []
