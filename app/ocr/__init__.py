"""Pluggable OCR recognizer contracts and implementations."""

from app.ocr.base import FieldAwareRecognizer, InvalidCellImageError, OCRBackendError, Recognizer
from app.ocr.mock import MockRecognizer
from app.ocr.paddle import PaddleOCRRecognizer

__all__ = [
    "InvalidCellImageError",
    "FieldAwareRecognizer",
    "MockRecognizer",
    "OCRBackendError",
    "PaddleOCRRecognizer",
    "Recognizer",
]
