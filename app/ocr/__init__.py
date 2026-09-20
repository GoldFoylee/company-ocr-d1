"""Pluggable OCR recognizer contracts and implementations."""

from app.ocr.base import InvalidCellImageError, Recognizer
from app.ocr.mock import MockRecognizer

__all__ = ["InvalidCellImageError", "MockRecognizer", "Recognizer"]
