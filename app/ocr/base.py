"""OCR boundary shared by business logic and recognizer implementations."""

from typing import Protocol, runtime_checkable

import numpy as np


class InvalidCellImageError(ValueError):
    """Raised when a recognizer receives data that is not a usable cell image."""


class OCRBackendError(RuntimeError):
    """Raised when the underlying OCR model itself fails during recognition.

    Distinct from :class:`InvalidCellImageError`: the input was a valid cell image,
    but the backend (model load, inference call, etc.) raised. Implementations
    should chain the original exception with ``raise OCRBackendError(...) from exc``.
    """


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


def validate_cell_image(cell_image: np.ndarray) -> None:
    """Reject inputs that cannot represent a cropped cell image.

    Shared by every :class:`Recognizer` implementation so the definition of "a usable
    cell image" lives in one place rather than being re-implemented per backend.
    """
    if not isinstance(cell_image, np.ndarray):
        raise InvalidCellImageError("cell image must be a NumPy array")
    if cell_image.size == 0:
        raise InvalidCellImageError("cell image must not be empty")
    if cell_image.ndim not in (2, 3):
        raise InvalidCellImageError("cell image must have two or three dimensions")
    if cell_image.ndim == 3 and cell_image.shape[2] not in (1, 3, 4):
        raise InvalidCellImageError("cell image must have 1, 3, or 4 channels")


def validate_confidence(confidence: float, *, name: str = "confidence") -> None:
    """Reject a confidence score outside the normalized ``[0.0, 1.0]`` range."""
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")
