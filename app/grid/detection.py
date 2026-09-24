"""Grid and cell detection: find ruled-sheet lines and derive cell boxes.

Uses the Hough line transform, the same technique already proven in
app/preprocessing/pipeline.py's deskew() -- one line-finding technique
across the module instead of introducing contour detection as a second,
unrelated one. Contour detection suits closed/filled shapes; ruled-sheet
lines are thin strokes, which is exactly what Hough is for.

The real log-book fixtures use one fixed 12-column/15-row form. Their thin,
light grid lines are interrupted by handwriting and therefore do not survive
the synthetic-grid Hough settings below. For that known template we detect
column dividers in the header, then require row candidates to agree across
several columns. The original generic Hough path remains the fallback for
other ruled grids and for the synthetic unit tests.

CellBox is axis-aligned, so perspective-warped phone photos remain a known
limitation. The golden fixtures are scans with modest line curvature rather
than meaningful keystone distortion; multi-column consensus keeps their
representative boundaries on the printed lines.
"""

from dataclasses import dataclass
from itertools import combinations
from math import log
from statistics import median
from typing import Final

import cv2
import numpy as np

_CANNY_LOW_THRESHOLD: Final = 50
_CANNY_HIGH_THRESHOLD: Final = 150
_HOUGH_VOTE_THRESHOLD: Final = 80
_HOUGH_MIN_LINE_LENGTH_RATIO: Final = 0.3
_HOUGH_MAX_LINE_GAP: Final = 10

# A line segment within this many degrees of horizontal/vertical is
# classified as a row/column boundary; steeper segments are ignored as
# noise (e.g. diagonal strokes from handwriting or cell content).
_MAX_LINE_ANGLE_DEVIATION_DEGREES: Final = 10.0

# Two detected line coordinates within this many pixels are treated as the
# same grid boundary (multiple Hough segments often detect one ruled line
# in pieces).
_BOUNDARY_CLUSTER_TOLERANCE_PX: Final = 15

# Fixed real form: 12 physical columns and 15 writable data rows. The header
# has the same vertical dividers, making it the cleanest place to detect them.
_TEMPLATE_COLUMN_BOUNDARY_COUNT: Final = 13
_TEMPLATE_DATA_ROW_BOUNDARY_COUNT: Final = 16
_TEMPLATE_MIN_IMAGE_DIMENSION_PX: Final = 1_000
_TEMPLATE_MAX_COLUMN_CANDIDATES: Final = 20
_TEMPLATE_RIGHT_EDGE_LIMIT_RATIO: Final = 0.98
_HEADER_SEARCH_TOP_RATIO: Final = 0.14
_HEADER_SEARCH_BOTTOM_RATIO: Final = 0.33
_HEADER_HOUGH_THRESHOLD: Final = 15
_HEADER_MIN_LINE_LENGTH_RATIO: Final = 0.2
_HEADER_MAX_LINE_GAP_PX: Final = 30
_TEMPLATE_LINE_ANGLE_DEVIATION_DEGREES: Final = 12.0

# Physical columns whose interiors are sampled when locating horizontal
# boundaries. Guest Name is deliberately omitted: its black anonymization
# blocks would overwhelm the ruled lines.
_ROW_CONSENSUS_COLUMNS: Final = (0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11)
_ROW_HOUGH_THRESHOLD: Final = 12
_ROW_MIN_LINE_LENGTH_RATIO: Final = 0.4
_ROW_MAX_LINE_GAP_PX: Final = 20
_ROW_MIN_COLUMN_CONSENSUS: Final = 3


@dataclass(frozen=True)
class GridLines:
    """Sorted pixel coordinates of detected row and column boundaries."""

    row_boundaries: list[int]
    column_boundaries: list[int]


@dataclass(frozen=True)
class CellBox:
    """One detected cell, addressed by its row/column index."""

    row: int
    column: int
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class _LineCandidate:
    coordinate: float
    support: float
    sources: frozenset[int] = frozenset()


def _to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _cluster_boundaries(coordinates: list[float]) -> list[int]:
    """Collapse nearby coordinates into single boundary positions.

    Takes ONE representative value per input line (see module docstring
    for why that's a known limitation under perspective warp), sorts them,
    then merges values within the cluster tolerance by averaging.
    """
    if not coordinates:
        return []

    sorted_coordinates = sorted(coordinates)
    clusters: list[list[float]] = [[sorted_coordinates[0]]]
    for coordinate in sorted_coordinates[1:]:
        if coordinate - clusters[-1][-1] <= _BOUNDARY_CLUSTER_TOLERANCE_PX:
            clusters[-1].append(coordinate)
        else:
            clusters.append([coordinate])

    return [round(sum(cluster) / len(cluster)) for cluster in clusters]


def _cluster_line_candidates(
    candidates: list[_LineCandidate], tolerance: float
) -> list[_LineCandidate]:
    """Cluster line candidates without chaining across a wide noisy band."""
    if not candidates:
        return []

    sorted_candidates = sorted(candidates, key=lambda candidate: candidate.coordinate)
    clusters: list[list[_LineCandidate]] = [[sorted_candidates[0]]]
    for candidate in sorted_candidates[1:]:
        # Compare with the first member, not the previous member. This caps a
        # cluster's diameter and prevents nearby text strokes from chaining
        # two distinct ruled lines together.
        if candidate.coordinate - clusters[-1][0].coordinate <= tolerance:
            clusters[-1].append(candidate)
        else:
            clusters.append([candidate])

    merged: list[_LineCandidate] = []
    for cluster in clusters:
        total_support = sum(candidate.support for candidate in cluster)
        weighted_coordinate = (
            sum(candidate.coordinate * candidate.support for candidate in cluster)
            / total_support
        )
        merged.append(
            _LineCandidate(
                coordinate=weighted_coordinate,
                support=total_support,
                sources=frozenset().union(*(candidate.sources for candidate in cluster)),
            )
        )
    return merged


def _range_penalty(value: float, lower: float, upper: float) -> float:
    if value < lower:
        return (lower - value) ** 2
    if value > upper:
        return (value - upper) ** 2
    return 0.0


def _select_template_columns(
    candidates: list[_LineCandidate], image_width: int, header_height: int
) -> list[int]:
    """Select the 13 dividers whose widths match the printed form."""
    if not (
        _TEMPLATE_COLUMN_BOUNDARY_COUNT
        <= len(candidates)
        <= _TEMPLATE_MAX_COLUMN_CANDIDATES
    ):
        return []

    best_score: float | None = None
    best_coordinates: list[int] = []
    for sequence in combinations(candidates, _TEMPLATE_COLUMN_BOUNDARY_COUNT):
        coordinates = [candidate.coordinate for candidate in sequence]
        widths = [
            right - left
            for left, right in zip(coordinates, coordinates[1:], strict=False)
        ]
        central_width = float(median(widths[3:10]))
        if central_width <= 0:
            continue

        ratios = [width / central_width for width in widths]
        penalty = sum(log(max(ratio, 0.01)) ** 2 for ratio in ratios[3:10])
        penalty += 4 * _range_penalty(ratios[0], 0.3, 0.75)
        penalty += 3 * _range_penalty(ratios[1], 0.75, 1.5)
        penalty += 4 * _range_penalty(ratios[2], 2.3, 6.0)
        penalty += 4 * _range_penalty(ratios[10], 1.8, 5.0)
        penalty += 3 * _range_penalty(ratios[11], 0.7, 2.2)
        penalty += 0.8 * log(ratios[10] / 2.7) ** 2
        penalty += 0.8 * log(ratios[11] / 1.2) ** 2

        span_ratio = (coordinates[-1] - coordinates[0]) / image_width
        penalty += 10 * max(0.7 - span_ratio, 0.0) ** 2
        penalty += 20 * max(coordinates[-1] / image_width - 0.985, 0.0) ** 2

        support = sum(
            min(candidate.support / header_height, 2.0) for candidate in sequence
        )
        score = penalty - 0.01 * support
        if best_score is None or score < best_score:
            best_score = score
            best_coordinates = [round(coordinate) for coordinate in coordinates]

    return best_coordinates


def _detect_template_columns(gray: np.ndarray) -> list[int]:
    height, width = gray.shape
    top = int(height * _HEADER_SEARCH_TOP_RATIO)
    bottom = int(height * _HEADER_SEARCH_BOTTOM_RATIO)
    header = gray[top:bottom]
    edges = cv2.Canny(header, 30, 100, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 720,
        threshold=_HEADER_HOUGH_THRESHOLD,
        minLineLength=int(header.shape[0] * _HEADER_MIN_LINE_LENGTH_RATIO),
        maxLineGap=_HEADER_MAX_LINE_GAP_PX,
    )
    if lines is None:
        return []

    candidates: list[_LineCandidate] = []
    for x1, y1, x2, y2 in lines[:, 0, :]:
        angle = abs(float(np.degrees(np.arctan2(y2 - y1, x2 - x1))))
        if abs(angle - 90.0) <= _TEMPLATE_LINE_ANGLE_DEVIATION_DEGREES:
            candidates.append(
                _LineCandidate(
                    coordinate=(x1 + x2) / 2,
                    support=float(np.hypot(x2 - x1, y2 - y1)),
                )
            )

    clustered = _cluster_line_candidates(candidates, max(10.0, width * 0.0035))
    # Sheet 005 includes the photographed page edge just to the right of the
    # form. Its several strong, parallel segments are not table dividers.
    clustered = [
        candidate
        for candidate in clustered
        if candidate.coordinate <= width * _TEMPLATE_RIGHT_EDGE_LIMIT_RATIO
    ]
    return _select_template_columns(clustered, width, header.shape[0])


def _detect_row_candidates(gray: np.ndarray, columns: list[int]) -> list[_LineCandidate]:
    height = gray.shape[0]
    candidates: list[_LineCandidate] = []
    for column in _ROW_CONSENSUS_COLUMNS:
        left = columns[column]
        right = columns[column + 1]
        margin = max(2, int((right - left) * 0.12))
        strip = gray[:, left + margin : right - margin]
        if strip.shape[1] < 2:
            continue

        edges = cv2.Canny(strip, 30, 100, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 720,
            threshold=_ROW_HOUGH_THRESHOLD,
            minLineLength=max(25, int(strip.shape[1] * _ROW_MIN_LINE_LENGTH_RATIO)),
            maxLineGap=_ROW_MAX_LINE_GAP_PX,
        )
        if lines is None:
            continue
        for x1, y1, x2, y2 in lines[:, 0, :]:
            angle = abs(float(np.degrees(np.arctan2(y2 - y1, x2 - x1))))
            if angle <= _MAX_LINE_ANGLE_DEVIATION_DEGREES:
                candidates.append(
                    _LineCandidate(
                        coordinate=(y1 + y2) / 2,
                        support=float(np.hypot(x2 - x1, y2 - y1)),
                        sources=frozenset((column,)),
                    )
                )

    clustered = _cluster_line_candidates(candidates, max(20.0, height * 0.01))
    return [
        candidate
        for candidate in clustered
        if len(candidate.sources) >= _ROW_MIN_COLUMN_CONSENSUS
        and candidate.coordinate > height * 0.12
    ]


def _select_template_rows(candidates: list[_LineCandidate], image_height: int) -> list[int]:
    """Select the 16 data-row boundaries, interpolating a clipped line if needed."""
    starts = [
        candidate
        for candidate in candidates
        if image_height * 0.19 <= candidate.coordinate <= image_height * 0.32
    ]
    ends = [
        candidate
        for candidate in candidates
        if image_height * 0.9 <= candidate.coordinate <= image_height * 1.01
    ]
    # Some scans end inside the final ruled border. The image edge is then the
    # only safe lower bound for the last row (sheet_002 is the real example).
    ends.append(_LineCandidate(coordinate=float(image_height - 1), support=0.0))

    best_score: float | None = None
    best_boundaries: list[int] = []
    for start in starts:
        for end in ends:
            step = (end.coordinate - start.coordinate) / 15
            if not image_height * 0.035 <= step <= image_height * 0.065:
                continue

            header_candidates = [
                candidate
                for candidate in candidates
                if len(candidate.sources) >= 5
                and 1.05 <= (start.coordinate - candidate.coordinate) / step <= 1.75
            ]
            if not header_candidates:
                continue

            tolerance = max(15.0, step * 0.3)
            score = max(len(candidate.sources) for candidate in header_candidates) * 0.15
            score += len(start.sources)
            score += len(end.sources) * 0.15
            boundaries: list[int] = []
            for index in range(_TEMPLATE_DATA_ROW_BOUNDARY_COUNT):
                predicted = start.coordinate + index * step
                nearest = min(
                    candidates,
                    key=lambda candidate: abs(candidate.coordinate - predicted),
                )
                distance = abs(nearest.coordinate - predicted)
                if distance <= tolerance:
                    score += 1 + len(nearest.sources) / len(_ROW_CONSENSUS_COLUMNS)
                    score -= distance / tolerance
                    boundaries.append(round(nearest.coordinate))
                else:
                    boundaries.append(round(predicted))

            if best_score is None or score > best_score:
                best_score = score
                best_boundaries = boundaries

    if not best_boundaries:
        return []
    best_boundaries[-1] = min(best_boundaries[-1], image_height - 1)
    return best_boundaries


def _detect_fixed_template(gray: np.ndarray) -> GridLines | None:
    if min(gray.shape) < _TEMPLATE_MIN_IMAGE_DIMENSION_PX:
        return None
    columns = _detect_template_columns(gray)
    if len(columns) != _TEMPLATE_COLUMN_BOUNDARY_COUNT:
        return None
    rows = _select_template_rows(_detect_row_candidates(gray, columns), gray.shape[0])
    if len(rows) != _TEMPLATE_DATA_ROW_BOUNDARY_COUNT:
        return None
    return GridLines(row_boundaries=rows, column_boundaries=columns)


def detect_grid_lines(image: np.ndarray) -> GridLines:
    """Detect ruled row/column boundaries via Hough line detection."""
    gray = _to_grayscale(image)
    fixed_template = _detect_fixed_template(gray)
    if fixed_template is not None:
        return fixed_template

    edges = cv2.Canny(gray, _CANNY_LOW_THRESHOLD, _CANNY_HIGH_THRESHOLD, apertureSize=3)
    min_line_length = int(min(gray.shape) * _HOUGH_MIN_LINE_LENGTH_RATIO)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=_HOUGH_VOTE_THRESHOLD,
        minLineLength=min_line_length,
        maxLineGap=_HOUGH_MAX_LINE_GAP,
    )

    if lines is None:
        return GridLines(row_boundaries=[], column_boundaries=[])

    row_coordinates: list[float] = []
    column_coordinates: list[float] = []
    for x1, y1, x2, y2 in lines[:, 0, :]:
        angle_degrees = abs(float(np.degrees(np.arctan2(y2 - y1, x2 - x1))))
        if angle_degrees <= _MAX_LINE_ANGLE_DEVIATION_DEGREES:
            row_coordinates.append((y1 + y2) / 2)
        elif abs(angle_degrees - 90.0) <= _MAX_LINE_ANGLE_DEVIATION_DEGREES:
            column_coordinates.append((x1 + x2) / 2)

    return GridLines(
        row_boundaries=_cluster_boundaries(row_coordinates),
        column_boundaries=_cluster_boundaries(column_coordinates),
    )


def detect_cells(image: np.ndarray) -> list[CellBox]:
    """Derive non-overlapping cell boxes from detected grid boundaries.

    Boxes are built directly from adjacent, sorted boundary pairs, so
    non-overlap and ordering are structural rather than merely asserted.
    """
    grid_lines = detect_grid_lines(image)
    cells: list[CellBox] = []
    for row in range(len(grid_lines.row_boundaries) - 1):
        for column in range(len(grid_lines.column_boundaries) - 1):
            cells.append(
                CellBox(
                    row=row,
                    column=column,
                    x1=grid_lines.column_boundaries[column],
                    y1=grid_lines.row_boundaries[row],
                    x2=grid_lines.column_boundaries[column + 1],
                    y2=grid_lines.row_boundaries[row + 1],
                )
            )
    return cells
