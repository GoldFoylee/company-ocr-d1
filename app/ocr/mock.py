"""Deterministic recognizer for pipeline development and tests."""

import numpy as np

from app.ocr.base import InvalidCellImageError


class MockRecognizer:
    """Return a configured result for every valid cell image."""

    def __init__(self, text: str = "MOCK_TEXT", confidence: float = 1.0) -> None:
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

        self._text = text
        self._confidence = float(confidence)

    def recognize(self, cell_image: np.ndarray) -> tuple[str, float]:
        """Validate the cell image and return the deterministic canned result."""
        self._validate_cell_image(cell_image)
        return self._text, self._confidence

    @staticmethod
    def _validate_cell_image(cell_image: np.ndarray) -> None:
        if not isinstance(cell_image, np.ndarray):
            raise InvalidCellImageError("cell image must be a NumPy array")
        if cell_image.size == 0:
            raise InvalidCellImageError("cell image must not be empty")
        if cell_image.ndim not in (2, 3):
            raise InvalidCellImageError("cell image must have two or three dimensions")
        if cell_image.ndim == 3 and cell_image.shape[2] not in (1, 3, 4):
            raise InvalidCellImageError("cell image must have 1, 3, or 4 channels")
