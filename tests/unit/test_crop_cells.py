"""Unit coverage for turning B2 cell boxes into tagged crops."""

import cv2
import numpy as np

from app.cropping import FIELD_NAMES, crop_cells
from app.grid import CellBox


def _two_row_grid() -> list[CellBox]:
    return [
        CellBox(
            row=row,
            column=column,
            x1=column * 20,
            y1=row * 30,
            x2=(column + 1) * 20,
            y2=(row + 1) * 30,
        )
        for row in range(2)
        for column in range(12)
    ]


def _image_with_one_populated_date() -> np.ndarray:
    image = np.full((60, 240, 3), 255, dtype=np.uint8)
    cv2.line(image, (23, 15), (37, 15), (0, 0, 0), thickness=3)
    return image


def test_crop_cells_tags_fields_in_physical_column_order() -> None:
    crops = crop_cells(_image_with_one_populated_date(), _two_row_grid())

    assert tuple(crop.field_name for crop in crops) == FIELD_NAMES
    assert [crop.column for crop in crops] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 10]
    assert all(crop.row == 0 for crop in crops)
    assert all(crop.image.shape == (30, 20, 3) for crop in crops)
    assert all(crop.excluded == (crop.field_name == "guest_name") for crop in crops)


def test_crop_cells_omits_unmapped_columns_and_blank_rows() -> None:
    crops = crop_cells(_image_with_one_populated_date(), _two_row_grid())

    assert {crop.column for crop in crops}.isdisjoint({11})
    assert crops[0].field_name == "ds_no"
    assert crops[0].column == 0
    assert {crop.row for crop in crops} == {0}


def test_toll_and_parking_share_one_independent_physical_crop() -> None:
    image = _image_with_one_populated_date()
    crops = crop_cells(image, _two_row_grid())
    toll = next(crop for crop in crops if crop.field_name == "toll")
    parking = next(crop for crop in crops if crop.field_name == "parking")

    assert toll.column == parking.column == 9
    assert toll.box == parking.box
    assert np.array_equal(toll.image, parking.image)
    assert not np.shares_memory(toll.image, parking.image)
    assert not np.shares_memory(toll.image, image)


def test_crop_cells_skips_rows_without_a_date_cell_box() -> None:
    cells = [cell for cell in _two_row_grid() if not (cell.row == 0 and cell.column == 1)]

    assert crop_cells(_image_with_one_populated_date(), cells) == []
