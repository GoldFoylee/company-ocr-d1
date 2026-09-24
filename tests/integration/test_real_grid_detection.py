"""Grid-detection regression coverage for the five real golden scans."""

from pathlib import Path

import cv2
import pytest

from app.grid import detect_cells, detect_grid_lines
from app.preprocessing import preprocess

FIXTURE_DIRECTORY = Path("tests/fixtures/anonymized")
FIXTURE_IDS = tuple(f"sheet_{number:03d}" for number in range(1, 6))
EXPECTED_COLUMN_BOUNDARIES = 13
EXPECTED_ROW_BOUNDARIES = 16
EXPECTED_CELL_COUNT = 15 * 12


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_real_fixture_grid_has_the_fixed_form_boundaries(fixture_id: str) -> None:
    image = cv2.imread(str(FIXTURE_DIRECTORY / f"{fixture_id}.jpg"))
    assert image is not None

    preprocessed = preprocess(image)
    grid = detect_grid_lines(preprocessed)

    assert len(grid.column_boundaries) == EXPECTED_COLUMN_BOUNDARIES
    assert len(grid.row_boundaries) == EXPECTED_ROW_BOUNDARIES
    assert grid.column_boundaries == sorted(set(grid.column_boundaries))
    assert grid.row_boundaries == sorted(set(grid.row_boundaries))
    assert all(0 <= x < preprocessed.shape[1] for x in grid.column_boundaries)
    assert all(0 <= y < preprocessed.shape[0] for y in grid.row_boundaries)


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_real_fixture_cells_are_ordered_non_overlapping_and_in_bounds(fixture_id: str) -> None:
    image = cv2.imread(str(FIXTURE_DIRECTORY / f"{fixture_id}.jpg"))
    assert image is not None

    preprocessed = preprocess(image)
    cells = detect_cells(preprocessed)

    assert len(cells) == EXPECTED_CELL_COUNT
    assert cells == sorted(cells, key=lambda cell: (cell.row, cell.column))
    for cell in cells:
        assert 0 <= cell.x1 < cell.x2 <= preprocessed.shape[1]
        assert 0 <= cell.y1 < cell.y2 <= preprocessed.shape[0]
