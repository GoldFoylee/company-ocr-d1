"""Turn physical grid cells into field-tagged image crops."""

from dataclasses import dataclass
from typing import Final, Literal

import cv2
import numpy as np

from app.grid import CellBox

FieldName = Literal[
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
]

FIELD_NAMES: Final[tuple[FieldName, ...]] = (
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

# Confirmed directly against the real fixture header. Physical columns 0 and
# 11 are DS No. and Guest Signature and are outside the requested extraction
# schema. The printed form has one combined "Toll Parking" column, so its one
# physical crop intentionally supplies both logical tags.
_PHYSICAL_COLUMN_FIELDS: Final[tuple[tuple[FieldName, ...], ...]] = (
    (),
    ("date",),
    ("guest_name",),
    ("start_time",),
    ("start_km",),
    ("close_time",),
    ("close_km",),
    ("total_km",),
    ("total_time",),
    ("toll", "parking"),
    ("journey_details",),
    (),
)

_DATE_COLUMN_INDEX: Final = 1
_EMPTY_DATE_CELL_DARK_PIXEL_RATIO: Final = 0.07
_EMPTY_DATE_CELL_SATURATED_PIXEL_RATIO: Final = 0.02
_INK_SATURATION_THRESHOLD: Final = 40
_CONTENT_INSET_RATIO: Final = 0.1


@dataclass(frozen=True)
class CroppedCell:
    """One cell image paired with its source geometry and logical field."""

    row: int
    column: int
    field_name: FieldName
    box: CellBox
    image: np.ndarray
    excluded: bool = False


def _crop(image: np.ndarray, box: CellBox) -> np.ndarray:
    return image[box.y1 : box.y2, box.x1 : box.x2].copy()


def _date_cell_has_content(image: np.ndarray, box: CellBox) -> bool:
    crop = _crop(image, box)
    height, width = crop.shape[:2]
    y_inset = max(2, int(height * _CONTENT_INSET_RATIO))
    x_inset = max(2, int(width * _CONTENT_INSET_RATIO))
    interior = crop[y_inset : height - y_inset, x_inset : width - x_inset]
    if interior.size == 0:
        return False
    saturated_pixel_ratio = 0.0
    if interior.ndim == 3:
        hsv = cv2.cvtColor(interior, cv2.COLOR_BGR2HSV)
        saturated_pixel_ratio = float(
            np.mean(hsv[:, :, 1] > _INK_SATURATION_THRESHOLD)
        )
        grayscale = cv2.cvtColor(interior, cv2.COLOR_BGR2GRAY)
    else:
        grayscale = interior
    dark_pixel_ratio = float(np.mean(grayscale < 128))
    return (
        dark_pixel_ratio >= _EMPTY_DATE_CELL_DARK_PIXEL_RATIO
        or saturated_pixel_ratio >= _EMPTY_DATE_CELL_SATURATED_PIXEL_RATIO
    )


def crop_cells(image: np.ndarray, cells: list[CellBox]) -> list[CroppedCell]:
    """Crop populated data rows and tag each requested logical field.

    The fixed form always prints 15 writable rows. A date is mandatory for a
    populated row, so trailing blank form rows are excluded by inspecting the
    date cell rather than by assuming a fixed row count.
    """
    cells_by_row: dict[int, list[CellBox]] = {}
    for cell in cells:
        cells_by_row.setdefault(cell.row, []).append(cell)

    cropped: list[CroppedCell] = []
    for row, row_cells in sorted(cells_by_row.items()):
        by_column = {cell.column: cell for cell in row_cells}
        date_cell = by_column.get(_DATE_COLUMN_INDEX)
        if date_cell is None or not _date_cell_has_content(image, date_cell):
            continue

        for column, field_names in enumerate(_PHYSICAL_COLUMN_FIELDS):
            box = by_column.get(column)
            if box is None:
                continue
            cell_image = _crop(image, box)
            for field_name in field_names:
                cropped.append(
                    CroppedCell(
                        row=row,
                        column=column,
                        field_name=field_name,
                        box=box,
                        image=cell_image.copy(),
                        excluded=field_name == "guest_name",
                    )
                )
    return cropped
