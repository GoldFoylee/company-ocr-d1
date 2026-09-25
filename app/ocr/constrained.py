"""Field-specific PP-OCRv6 CTC decoding with the original model dictionary.

PaddleOCR 3.x binds its character dictionary to the model's output indices.
Replacing that dictionary with a shorter file at inference would mislabel those
indices. This variant instead masks unwanted CTC classes *before* argmax, then
uses PaddleX's original decoder and its unchanged character-index mapping.
"""

from typing import Any, Final

import numpy as np

from app.ocr.paddle import OCRPredictor, PaddleOCRRecognizer, _build_predictor, _mkldnn_enabled

CONSTRAINED_FIELDS: Final = frozenset({"date", "start_time", "close_time"})
# Preserve the original CTC blank (index 0). These are the only visible classes
# admitted for the date and time experiment; no parser or format correction is
# applied to the model output. Both '/' and '1' remain possible choices.
_ALLOWED_CHARACTERS: Final = frozenset("0123456789/:-.|")
_REQUIRED_CHARACTERS: Final = frozenset("0123456789/:")


class ConstrainedCTCDecode:
    """Mask PP-OCRv6 probabilities while retaining the trained index mapping."""

    def __init__(self, original_decoder: Any) -> None:
        characters = tuple(original_decoder.character)
        if not characters or characters[0] != "blank":
            raise ValueError("PP-OCRv6 CTC decoder must have blank at index 0")
        missing = _REQUIRED_CHARACTERS - set(characters)
        if missing:
            raise ValueError(f"PP-OCRv6 dictionary lacks required characters: {sorted(missing)}")
        self._original = original_decoder
        self._allowed_indices = np.array(
            [
                index
                for index, char in enumerate(characters)
                if index == 0 or char in _ALLOWED_CHARACTERS
            ],
            dtype=np.intp,
        )
        self._class_count = len(characters)

    def __call__(self, predictions: Any, **kwargs: Any) -> Any:
        # PaddleX 3.7's CTCLabelDecode reads predictions[0]. Copy first so the
        # runner's output and any other consumer remain untouched.
        probabilities = np.array(predictions[0], copy=True)
        if probabilities.ndim != 3 or probabilities.shape[-1] != self._class_count:
            raise ValueError(
                "PP-OCRv6 output classes do not match its trained character dictionary"
            )
        allowed = np.zeros(self._class_count, dtype=bool)
        allowed[self._allowed_indices] = True
        probabilities[..., ~allowed] = -np.inf
        # Delegate CTC duplicate/blank handling and confidence calculation to
        # the exact decoder used by the unconstrained recognizer.
        return self._original((probabilities,), **kwargs)


def _install_constrained_decoder(model: OCRPredictor) -> None:
    """Install the mask on one PaddleOCR 3.7 predictor instance, not globally."""
    try:
        pipeline = model.paddlex_pipeline  # type: ignore[attr-defined]
        internal_pipeline = pipeline._pipeline
        text_rec_model = internal_pipeline.text_rec_model
        text_rec_model.post_op = ConstrainedCTCDecode(text_rec_model.post_op)
    except AttributeError as exc:
        raise RuntimeError(
            "PaddleOCR/PaddleX predictor layout changed; cannot constrain CTC decoding"
        ) from exc


class ConstrainedPaddleOCRRecognizer:
    """Route only date and clock fields through a constrained PP-OCRv6 decoder."""

    def __init__(
        self,
        *,
        general_model: OCRPredictor | None = None,
        constrained_model: OCRPredictor | None = None,
        model_tier: str = "medium",
        enable_mkldnn: bool | None = None,
    ) -> None:
        mkldnn = _mkldnn_enabled(enable_mkldnn)
        general_predictor = (
            general_model if general_model is not None else _build_predictor(model_tier, mkldnn)
        )
        self._general = PaddleOCRRecognizer(model=general_predictor)
        constrained_predictor = (
            constrained_model
            if constrained_model is not None
            else _build_predictor(model_tier, mkldnn)
        )
        _install_constrained_decoder(constrained_predictor)
        self._constrained = PaddleOCRRecognizer(model=constrained_predictor)

    def recognize(
        self, cell_image: np.ndarray, *, field_name: str | None = None
    ) -> tuple[str, float]:
        recognizer = self._constrained if field_name in CONSTRAINED_FIELDS else self._general
        return recognizer.recognize(cell_image, field_name=field_name)
