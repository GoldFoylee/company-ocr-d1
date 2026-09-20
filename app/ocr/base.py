"""OCR boundary shared by business logic and recognizer implementations."""

from typing import Protocol, runtime_checkable

import numpy as np


class InvalidCellImageError(ValueError):
    """Raised when a recognizer receives data that is not a usable cell image."""


@runtime_checkable
class Recognizer(Protocol):
    """Contract implemented by every OCR backend.

    Business logic depends on this protocol rather than on a concrete OCR library.
    Implementations return recognized text and a normalized confidence score.
    """

    def recognize(self, cell_image: np.ndarray) -> tuple[str, float]:
        """Recognize a cropped cell image as ``(text, confidence)``.

        Confidence must be between 0.0 and 1.0. Implementations should raise
        :class:`InvalidCellImageError` when the input cannot represent an image.
        """
        ...
