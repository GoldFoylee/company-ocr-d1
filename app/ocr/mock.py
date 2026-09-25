"""Deterministic recognizer for pipeline development and tests."""

import numpy as np

from app.ocr.base import validate_cell_image, validate_confidence


class MockRecognizer:
    """Return a configured result for every valid cell image."""

    def __init__(self, text: str = "MOCK_TEXT", confidence: float = 1.0) -> None:
        validate_confidence(confidence)

        self._text = text
        self._confidence = float(confidence)

    def recognize(self, cell_image: np.ndarray) -> tuple[str, float]:
        """Validate the cell image and return the deterministic canned result."""
        validate_cell_image(cell_image)
        return self._text, self._confidence
