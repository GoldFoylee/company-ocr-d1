"""PP-OCRv6 (PaddleOCR) recognizer: detect and recognize text within one cell crop.

Uses the full ``PaddleOCR`` detect+recognize pipeline per cell, not the single-line
``TextRecognition`` module alone. Cropped cells routinely hold more than one text
line -- e.g. a start time written as "8:00" over "AM" on two lines, or wrapped
journey details -- and ``TextRecognition`` recognizes exactly one line, silently
truncating the rest. Detection on an already-tight crop is not free either: text
near a cell's edge can be clipped by the crop boundary before the model ever sees
it. See docs/baselines/ppocrv6-baseline.md for how often that shows up in practice
against the real golden fixtures.

Document orientation classification, unwarping, and textline orientation are all
disabled: app/preprocessing/pipeline.py already deskews the source image before
cropping, and cells are small, already-axis-aligned crops -- running three extra
classifier models per cell would only add latency, not accuracy, here.
"""

from dataclasses import dataclass
from typing import Any, Final, Protocol

import numpy as np

from app.ocr.base import OCRBackendError, validate_cell_image, validate_confidence

# PP-OCRv6_medium: the most accurate of the three PP-OCRv6 tiers (see the PR
# description for the tiny/small/medium accuracy comparison) -- the fairest
# baseline for later models (e.g. TrOCR, fine-tuning) to be compared against.
_DEFAULT_MODEL_TIER: Final = "medium"


class OCRPredictor(Protocol):
    """The subset of PaddleOCR's ``predict()`` interface this module depends on.

    Lets unit tests supply a fake predictor directly, with no monkeypatching of
    the real ``paddleocr`` package.
    """

    def predict(self, input: np.ndarray) -> list[Any]: ...


@dataclass(frozen=True, slots=True)
class _TextLine:
    """One recognized text line, positioned for reading-order sorting."""

    text: str
    score: float
    top: float
    left: float


def _build_predictor(model_tier: str) -> OCRPredictor:
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise ImportError(
            "paddleocr is not installed. Install it via "
            "`pip install -r requirements.txt` (it pulls in paddlepaddle as well) "
            "before using PaddleOCRRecognizer, or pass an explicit `model=`."
        ) from exc

    return PaddleOCR(
        text_detection_model_name=f"PP-OCRv6_{model_tier}_det",
        text_recognition_model_name=f"PP-OCRv6_{model_tier}_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        # Verified during this task on the dev container (linux/amd64 -- x86_64
        # paddlepaddle has no linux/arm64 wheel, so on an Apple Silicon host this
        # runs under QEMU emulation): the default oneDNN (MKLDNN) CPU path raises
        # "NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute
        # not support [pir::ArrayAttribute<pir::DoubleAttribute>]" on every real
        # inference call. Disabling it resolves the error and inference is still
        # sub-second per crop. Whether this also reproduces on native x86_64 (e.g.
        # CI) is unverified from this session; kept off unconditionally since it
        # costs little on the crop sizes this module handles.
        enable_mkldnn=False,
    )


def _poly_top_left(poly: Any) -> tuple[float, float]:
    """Return a text line's (top, left) corner for reading-order sorting."""
    points = np.asarray(poly, dtype=float)
    return float(points[:, 1].min()), float(points[:, 0].min())


def _extract_lines(predict_results: list[Any]) -> list[_TextLine]:
    """Flatten PaddleOCR's per-image results into non-empty, positioned text lines."""
    lines: list[_TextLine] = []
    for result in predict_results:
        texts = result["rec_texts"]
        scores = result["rec_scores"]
        polys = result["rec_polys"]
        for text, score, poly in zip(texts, scores, polys, strict=True):
            if not text:
                continue
            top, left = _poly_top_left(poly)
            lines.append(_TextLine(text=text, score=float(score), top=top, left=left))
    return lines


def _join_reading_order(lines: list[_TextLine]) -> tuple[str, float]:
    """Join lines top-to-bottom then left-to-right; confidence is the weakest line's.

    Min, not mean: flagging (app/validation/flagging.py) should trigger review when
    any part of a multi-line cell is uncertain, not only when the average is.
    """
    ordered = sorted(lines, key=lambda line: (line.top, line.left))
    text = " ".join(line.text for line in ordered)
    confidence = min(line.score for line in ordered)
    return text, confidence


class PaddleOCRRecognizer:
    """PP-OCRv6-backed :class:`~app.ocr.base.Recognizer` for cropped cell images."""

    def __init__(
        self,
        model: OCRPredictor | None = None,
        *,
        model_tier: str = _DEFAULT_MODEL_TIER,
    ) -> None:
        """Build the recognizer.

        ``model`` lets tests and callers supply a predictor directly (e.g. a fake,
        or a pre-built ``PaddleOCR`` instance to share across many recognitions).
        When omitted, a real PP-OCRv6 pipeline is constructed lazily -- importing
        ``paddleocr`` only here, never at module import time, so ``import app.ocr``
        stays free of the OCR framework.
        """
        self._predictor = model if model is not None else _build_predictor(model_tier)

    def recognize(self, cell_image: np.ndarray) -> tuple[str, float]:
        """Recognize a cropped cell image as ``(text, confidence)``.

        Returns ``("", 0.0)`` when nothing is recognized -- an honest "found
        nothing", not a fabricated fallback. Zero confidence sends the field to
        review under the existing flagging threshold (app/validation/flagging.py).
        """
        validate_cell_image(cell_image)

        try:
            predict_results = self._predictor.predict(input=cell_image)
        except Exception as exc:
            raise OCRBackendError(f"PP-OCRv6 inference failed: {exc}") from exc

        lines = _extract_lines(predict_results)
        text, confidence = _join_reading_order(lines) if lines else ("", 0.0)

        # Guards the Recognizer contract even though a well-behaved backend never
        # violates it: a fake or a misbehaving future backend should fail loudly
        # here, not propagate a nonsensical confidence into flagging.
        validate_confidence(confidence, name="ocr_confidence")
        return text, confidence
