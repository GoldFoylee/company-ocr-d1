"""Contract tests for the deterministic OCR mock."""

import numpy as np
import pytest

from app.ocr.base import InvalidCellImageError, Recognizer
from app.ocr.mock import MockRecognizer


def test_mock_recognizer_satisfies_protocol_and_returns_canned_result() -> None:
    recognizer = MockRecognizer(text="ABC-123", confidence=0.91)
    cell_image = np.zeros((24, 80, 3), dtype=np.uint8)

    first_result = recognizer.recognize(cell_image)
    second_result = recognizer.recognize(cell_image)

    assert isinstance(recognizer, Recognizer)
    assert first_result == ("ABC-123", 0.91)
    assert second_result == first_result
    assert isinstance(first_result, tuple)
    assert isinstance(first_result[0], str)
    assert isinstance(first_result[1], float)


@pytest.mark.parametrize(
    "cell_image",
    [
        np.empty((0, 0), dtype=np.uint8),
        np.empty((10, 0, 3), dtype=np.uint8),
    ],
)
def test_mock_recognizer_rejects_empty_images(cell_image: np.ndarray) -> None:
    with pytest.raises(InvalidCellImageError, match="must not be empty"):
        MockRecognizer().recognize(cell_image)


@pytest.mark.parametrize(
    "cell_image",
    [
        b"not-an-image",
        np.zeros((10,), dtype=np.uint8),
        np.zeros((10, 10, 2), dtype=np.uint8),
    ],
)
def test_mock_recognizer_rejects_corrupt_images(cell_image: object) -> None:
    with pytest.raises(InvalidCellImageError):
        MockRecognizer().recognize(cell_image)  # type: ignore[arg-type]


def test_mock_recognizer_accepts_grayscale_images() -> None:
    result = MockRecognizer().recognize(np.zeros((24, 80), dtype=np.uint8))

    assert result == ("MOCK_TEXT", 1.0)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_mock_recognizer_rejects_invalid_canned_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        MockRecognizer(confidence=confidence)
