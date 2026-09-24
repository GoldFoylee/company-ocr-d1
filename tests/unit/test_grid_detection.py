"""Grid/cell detection tests against synthetically generated ruled grids.

The synthetic samples preserve coverage of the generic Hough fallback and
known-coordinate assertions; real scanned-sheet coverage lives in the
integration suite.

One test (test_detect_grid_lines_representative_coordinate_is_inaccurate_
under_perspective_warp) deliberately documents a known limitation rather
than proving correctness: detect_grid_lines() collapses each detected line
to one representative coordinate, which is a fine approximation for a
uniformly tilted line but not for one warped by perspective, where its
position genuinely varies along its length. See app/grid/detection.py's
module docstring and the PR description for what this means on real
keystone-warped photos.
"""

import cv2
import numpy as np

from app.grid import detect_cells, detect_grid_lines

POSITION_TOLERANCE_PX = 5
WARP_INACCURACY_THRESHOLD_PX = 10


def make_grid_sample(
    rows: int = 5,
    columns: int = 4,
    cell_width: int = 60,
    cell_height: int = 40,
    margin: int = 20,
) -> tuple[np.ndarray, list[int], list[int]]:
    """A synthetic ruled grid with known row/column boundary pixel positions."""
    width = columns * cell_width + 2 * margin
    height = rows * cell_height + 2 * margin
    image = np.full((height, width), 255, dtype=np.uint8)

    row_boundaries = [margin + row * cell_height for row in range(rows + 1)]
    column_boundaries = [margin + col * cell_width for col in range(columns + 1)]

    for y in row_boundaries:
        cv2.line(image, (margin, y), (width - margin, y), 0, 2)
    for x in column_boundaries:
        cv2.line(image, (x, margin), (x, height - margin), 0, 2)

    return image, row_boundaries, column_boundaries


def _perspective_matrix(width: int, height: int, top_inset_ratio: float) -> np.ndarray:
    """A trapezoid warp: top edge pulled inward, bottom edge unchanged.

    Mirrors what B1's own before/after images visibly showed for
    uncorrected perspective distortion.
    """
    inset = width * top_inset_ratio
    src = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    dst = np.float32([[inset, 0], [width - inset, 0], [width, height], [0, height]])
    return cv2.getPerspectiveTransform(src, dst)


def warp_perspective_trapezoid(image: np.ndarray, top_inset_ratio: float) -> np.ndarray:
    height, width = image.shape[:2]
    matrix = _perspective_matrix(width, height, top_inset_ratio)
    return cv2.warpPerspective(
        image, matrix, (width, height), borderMode=cv2.BORDER_CONSTANT, borderValue=255
    )


def _true_warped_x(matrix: np.ndarray, x: float, y: float) -> float:
    point = np.array([[[x, y]]], dtype=np.float32)
    transformed = cv2.perspectiveTransform(point, matrix)
    return float(transformed[0, 0, 0])


def test_detect_grid_lines_finds_correct_row_and_column_counts() -> None:
    image, expected_rows, expected_columns = make_grid_sample(rows=5, columns=4)

    grid = detect_grid_lines(image)

    assert len(grid.row_boundaries) == len(expected_rows)
    assert len(grid.column_boundaries) == len(expected_columns)


def test_detect_grid_lines_boundaries_close_to_known_positions() -> None:
    image, expected_rows, expected_columns = make_grid_sample(rows=5, columns=4)

    grid = detect_grid_lines(image)

    for detected, expected in zip(grid.row_boundaries, expected_rows, strict=True):
        assert abs(detected - expected) <= POSITION_TOLERANCE_PX
    for detected, expected in zip(grid.column_boundaries, expected_columns, strict=True):
        assert abs(detected - expected) <= POSITION_TOLERANCE_PX


def test_detect_grid_lines_returns_empty_when_no_lines_found() -> None:
    blank = np.full((100, 100), 255, dtype=np.uint8)

    grid = detect_grid_lines(blank)

    assert grid.row_boundaries == []
    assert grid.column_boundaries == []


def test_detect_cells_returns_expected_count() -> None:
    image, expected_rows, expected_columns = make_grid_sample(rows=5, columns=4)

    cells = detect_cells(image)

    assert len(cells) == (len(expected_rows) - 1) * (len(expected_columns) - 1)


def test_detect_cells_are_ordered_row_major() -> None:
    image, _, expected_columns = make_grid_sample(rows=5, columns=4)
    num_columns = len(expected_columns) - 1

    cells = detect_cells(image)

    for index, cell in enumerate(cells):
        assert cell.row == index // num_columns
        assert cell.column == index % num_columns


def test_detect_cells_are_non_overlapping_and_well_formed() -> None:
    image, _, _ = make_grid_sample(rows=5, columns=4)

    cells = detect_cells(image)

    for cell in cells:
        assert cell.x1 < cell.x2
        assert cell.y1 < cell.y2

    cells_by_row: dict[int, list] = {}
    for cell in cells:
        cells_by_row.setdefault(cell.row, []).append(cell)
    for row_cells in cells_by_row.values():
        row_cells.sort(key=lambda cell: cell.column)
        for left, right in zip(row_cells, row_cells[1:], strict=False):
            assert left.x2 <= right.x1


def test_detect_grid_lines_handles_color_images() -> None:
    image, expected_rows, expected_columns = make_grid_sample(rows=5, columns=4)
    color = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

    grid = detect_grid_lines(color)

    assert len(grid.row_boundaries) == len(expected_rows)
    assert len(grid.column_boundaries) == len(expected_columns)


def test_detect_grid_lines_returns_empty_columns_when_only_horizontal_lines_present() -> None:
    width, height, margin = 200, 150, 20
    image = np.full((height, width), 255, dtype=np.uint8)
    for y in (margin, height - margin):
        cv2.line(image, (margin, y), (width - margin, y), 0, 2)

    grid = detect_grid_lines(image)

    assert len(grid.row_boundaries) == 2
    assert grid.column_boundaries == []


def test_detect_grid_lines_representative_coordinate_is_inaccurate_under_perspective_warp() -> (
    None
):
    """Documents the known gap inherited from B1's deskew(): a single
    representative coordinate per line is a poor approximation once a line
    is genuinely warped, not just tilted. Detection should still run
    without crashing and produce structurally valid output, but the
    detected column position will sit inaccurately between its true top
    and bottom position -- this is the expected failure mode, not a bug
    fixed here.

    Uses the leftmost column boundary, which moves the most under this
    trapezoid warp (edges shift more than the vertical center line does).
    """
    top_inset_ratio = 0.2
    image, _, expected_columns = make_grid_sample(rows=4, columns=3)
    height, width = image.shape[:2]
    matrix = _perspective_matrix(width, height, top_inset_ratio)
    warped = warp_perspective_trapezoid(image, top_inset_ratio)

    grid = detect_grid_lines(warped)

    assert len(grid.column_boundaries) >= 1

    edge_column_x = expected_columns[0]
    true_top_x = _true_warped_x(matrix, edge_column_x, 0)
    true_bottom_x = _true_warped_x(matrix, edge_column_x, height)
    midpoint = (true_top_x + true_bottom_x) / 2

    closest_detected_x = min(grid.column_boundaries, key=lambda x: abs(x - midpoint))

    assert abs(closest_detected_x - true_top_x) > WARP_INACCURACY_THRESHOLD_PX
    assert abs(closest_detected_x - true_bottom_x) > WARP_INACCURACY_THRESHOLD_PX
