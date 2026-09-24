"""Crop detected log-sheet cells and attach their logical field tags."""

from app.cropping.cells import FIELD_NAMES, CroppedCell, FieldName, crop_cells

__all__ = ["FIELD_NAMES", "CroppedCell", "FieldName", "crop_cells"]
