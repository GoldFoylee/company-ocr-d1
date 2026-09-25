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
from app.validation.engine import ValidationResult


@pytest.mark.parametrize(
    ("field_name", "expected_rule"),
    [
        ("ds_no", "unique_ds_no"),
        ("start_km", "kilometre_total"),
        ("close_km", "kilometre_total"),
        ("total_km", "kilometre_total"),
        ("start_time", "time_total"),
        ("close_time", "time_total"),
        ("total_time", "time_total"),
        ("date", "non_decreasing_dates"),
        ("toll", "no_applicable_rule"),
        ("parking", "no_applicable_rule"),
        ("journey_details", "no_applicable_rule"),
    ],
)
def test_existing_rules_map_only_to_the_fields_they_check(
    field_name: str, expected_rule: str
) -> None:
    km_rule = ValidationResult("kilometre_total", False, "km mismatch", row_number=2)
    time_rule = ValidationResult("time_total", False, "bad category", row_number=2)
    date_rule = ValidationResult("non_decreasing_dates", False, "bad date")
    ds_rule = ValidationResult("unique_ds_no", False, "duplicate DS.No")

    result = pipeline._validation_for_field(
        field_name,
        2,
        {("kilometre_total", 2): km_rule, ("time_total", 2): time_rule},
        date_rule,
        ds_rule,
    )

    assert result.rule == expected_rule
    assert result.passed is (expected_rule == "no_applicable_rule")


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
