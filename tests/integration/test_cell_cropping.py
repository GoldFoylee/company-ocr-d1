"""Real-fixture coverage for preprocessing, grid detection, and cell cropping."""

import json
from pathlib import Path

import cv2
import pytest

from app.grid import detect_cells, detect_grid_lines
from app.preprocessing import preprocess

FIXTURE_DIRECTORY = Path("tests/fixtures/anonymized")
FIXTURE_IDS = tuple(f"sheet_{number:03d}" for number in range(1, 6))
EXPECTED_FIELDS = (
    "date",
    "guest_name",
    "start_time",
    "start_km",
    "close_time",
    "close_km",
    "total_km",
    "total_time",
    "toll",
    "parking",
    "journey_details",
)


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_real_fixture_pipeline_crops_every_populated_row(fixture_id: str) -> None:
    """Exercise the complete real-data path against every anonymized golden sheet."""
    from app.cropping import crop_cells

    image = cv2.imread(str(FIXTURE_DIRECTORY / f"{fixture_id}.jpg"))
    assert image is not None
    ground_truth = json.loads((FIXTURE_DIRECTORY / f"{fixture_id}.json").read_text())
    expected_row_count = len(ground_truth["rows"])

    preprocessed = preprocess(image)
    grid = detect_grid_lines(preprocessed)
    cells = detect_cells(preprocessed)
    crops = crop_cells(preprocessed, cells)

    assert len(grid.column_boundaries) == 13
    assert len(grid.row_boundaries) == 16
    assert len(crops) == expected_row_count * len(EXPECTED_FIELDS)
    assert sorted({crop.row for crop in crops}) == list(range(expected_row_count))

    for row in range(expected_row_count):
        row_crops = [crop for crop in crops if crop.row == row]
        assert tuple(crop.field_name for crop in row_crops) == EXPECTED_FIELDS
        assert all(crop.image.size > 0 for crop in row_crops)
        assert all(crop.excluded == (crop.field_name == "guest_name") for crop in row_crops)
