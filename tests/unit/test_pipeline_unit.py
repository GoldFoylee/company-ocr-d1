"""Pipeline mapping and rollback behavior at its stage boundaries."""

from datetime import date
from pathlib import Path

import cv2
import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.pipeline as pipeline
from app.cropping import CroppedCell
from app.database import Base
from app.grid import CellBox, GridLines
from app.models import Sheet
from app.ocr.mock import MockRecognizer


def _stub_single_cell_stages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    source = tmp_path / "input.jpg"
    image = np.full((20, 20, 3), 255, dtype=np.uint8)
    assert cv2.imwrite(str(source), image)
    box = CellBox(row=0, column=1, x1=0, y1=0, x2=10, y2=10)
    monkeypatch.setattr(pipeline, "preprocess", lambda image: image)
    monkeypatch.setattr(
        pipeline, "detect_grid_lines", lambda image: GridLines([0, 10], [0, 10])
    )
    monkeypatch.setattr(pipeline, "detect_cells", lambda image: [box])
    monkeypatch.setattr(
        pipeline,
        "crop_cells",
        lambda image, cells: [
            CroppedCell(row=0, column=1, field_name="date", box=box, image=image[:10, :10])
        ],
    )
    return source


def test_incomplete_crops_roll_back_sheet_and_remove_written_images(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _stub_single_cell_stages(monkeypatch, tmp_path)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            with pytest.raises(ValueError, match="ds_no"):
                pipeline.run_sheet_pipeline(
                    image_path=source,
                    crop_root=tmp_path / "crops",
                    db=db,
                    recognizer=MockRecognizer(),
                    vehicle="Synthetic Vehicle",
                    branch="Synthetic Branch",
                    sheet_date=date(2026, 9, 24),
                    roster_query="Morgon Alder",
                    roster_names=("Morgan Alder",),
                )
            assert db.scalars(select(Sheet)).all() == []
            assert not list((tmp_path / "crops").rglob("*.jpg"))
    finally:
        engine.dispose()


def test_pipeline_passes_field_name_to_optional_field_aware_recognizer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _stub_single_cell_stages(monkeypatch, tmp_path)

    class FieldAwareSpy:
        def __init__(self) -> None:
            self.fields: list[str] = []

        def recognize(self, cell_image: np.ndarray) -> tuple[str, float]:
            raise AssertionError("generic read should not be used")

        def recognize_field(self, field_name: str, cell_image: np.ndarray) -> tuple[str, float]:
            self.fields.append(field_name)
            return "1/8/26", 0.9

    recognizer = FieldAwareSpy()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            with pytest.raises(ValueError, match="ds_no"):
                pipeline.run_sheet_pipeline(
                    image_path=source,
                    crop_root=tmp_path / "crops",
                    db=db,
                    recognizer=recognizer,
                    vehicle="Synthetic Vehicle",
                    branch="Synthetic Branch",
                    sheet_date=date(2026, 9, 24),
                    roster_query="Morgon Alder",
                    roster_names=("Morgan Alder",),
                )
        assert recognizer.fields == ["date"]
    finally:
        engine.dispose()


def test_existing_crop_directory_is_preserved_on_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _stub_single_cell_stages(monkeypatch, tmp_path)
    existing_directory = tmp_path / "crops" / "sheet_000001"
    existing_directory.mkdir(parents=True)
    marker = existing_directory / "keep.txt"
    marker.write_text("existing data")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            with pytest.raises(FileExistsError):
                pipeline.run_sheet_pipeline(
                    image_path=source,
                    crop_root=tmp_path / "crops",
                    db=db,
                    recognizer=MockRecognizer(),
                    vehicle="Synthetic Vehicle",
                    branch="Synthetic Branch",
                    sheet_date=date(2026, 9, 24),
                    roster_query="Morgon Alder",
                    roster_names=("Morgan Alder",),
                )
            assert db.scalars(select(Sheet)).all() == []
            assert marker.read_text() == "existing data"
    finally:
        engine.dispose()
