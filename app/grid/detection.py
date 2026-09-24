"""Grid and cell detection: find ruled-sheet lines and derive cell boxes.

Uses the Hough line transform, the same technique already proven in
app/preprocessing/pipeline.py's deskew() -- one line-finding technique
across the module instead of introducing contour detection as a second,
unrelated one. Contour detection suits closed/filled shapes; ruled-sheet
lines are thin strokes, which is exactly what Hough is for.

Known gap, inherited from B1's deskew(): deskew() only corrects in-plane
rotation, not perspective/keystone distortion from off-angle phone
photography. This module's line clustering takes ONE representative
coordinate per detected line segment (its mean y for a horizontal line, its
mean x for a vertical one). That is a fine approximation when a line is
uniformly tilted, but not when a line is warped by perspective -- there,
its y (or x) genuinely varies along its own length, and collapsing it to
one number is a real information loss, not just noise. See the PR
description for what this is expected to do on real keystone-warped
photos (likely under/over-counting boundaries, or misplacing them) and
why that isn't being solved here.
"""

from dataclasses import dataclass
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


def detect_grid_lines(image: np.ndarray) -> GridLines:
    """Detect ruled row/column boundaries via Hough line detection."""
    gray = _to_grayscale(image)
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
