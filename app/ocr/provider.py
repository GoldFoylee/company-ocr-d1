"""Application-level OCR dependency wiring."""

from functools import lru_cache

from app.ocr.base import Recognizer


@lru_cache(maxsize=1)
def get_recognizer() -> Recognizer:
    """Build the production recognizer once, on the first upload request."""
    from app.ocr.paddle import PaddleOCRRecognizer

    return PaddleOCRRecognizer()
