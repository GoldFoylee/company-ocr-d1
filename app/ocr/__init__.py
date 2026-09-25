"""Pluggable OCR recognizer contracts and implementations."""

from app.ocr.base import InvalidCellImageError, OCRBackendError, Recognizer
from app.ocr.constrained import ConstrainedPaddleOCRRecognizer
from app.ocr.mock import MockRecognizer
from app.ocr.paddle import PaddleOCRRecognizer

__all__ = [
    "InvalidCellImageError",
    "ConstrainedPaddleOCRRecognizer",
    "MockRecognizer",
    "OCRBackendError",
    "PaddleOCRRecognizer",
    "Recognizer",
]
