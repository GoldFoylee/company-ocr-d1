"""Check field routing and the trained-index CTC mask without loading PaddleOCR."""

from types import SimpleNamespace

import numpy as np
import pytest

from app.ocr.base import Recognizer
from app.ocr.constrained import ConstrainedCTCDecode, ConstrainedPaddleOCRRecognizer


class FakeCTCDecoder:
    character = ["blank", *"0123456789", "/", ":", "A"]

    def __call__(self, predictions, **kwargs):
        probabilities = predictions[0]
        indices = probabilities.argmax(axis=-1)[0]
        values = probabilities.max(axis=-1)[0]
        selected = [
            (self.character[index], values[pos])
            for pos, index in enumerate(indices)
            if index
        ]
        return [
            "".join(char for char, _ in selected),
        ], [float(np.mean([score for _, score in selected])) if selected else 0.0]


def test_ctc_mask_suppresses_unrelated_class_before_argmax() -> None:
    decoder = ConstrainedCTCDecode(FakeCTCDecoder())
    probabilities = np.zeros((1, 1, len(FakeCTCDecoder.character)), dtype=np.float32)
    probabilities[0, 0, 13] = 0.9  # A is the unrestricted winner.
    probabilities[0, 0, 11] = 0.7  # / is the best allowed class.

    texts, scores = decoder((probabilities,))
    assert texts == ["/"]
    assert scores == pytest.approx([0.7])
    assert probabilities[0, 0, 13] == pytest.approx(0.9)  # runner output stays untouched


def test_ctc_mask_cannot_force_slash_over_digit_one() -> None:
    decoder = ConstrainedCTCDecode(FakeCTCDecoder())
    probabilities = np.zeros((1, 1, len(FakeCTCDecoder.character)), dtype=np.float32)
    probabilities[0, 0, 2] = 0.9  # trained index for 1
    probabilities[0, 0, 11] = 0.7  # trained index for /

    assert decoder((probabilities,))[0] == ["1"]


class FakePredictor:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0
        rec_model = SimpleNamespace(post_op=FakeCTCDecoder())
        self.paddlex_pipeline = SimpleNamespace(
            _pipeline=SimpleNamespace(text_rec_model=rec_model)
        )

    def predict(self, input: np.ndarray):
        self.calls += 1
        return [
            {
                "rec_texts": [self.text],
                "rec_scores": [0.8],
                "rec_polys": [np.array([[0, 0], [2, 0], [2, 2], [0, 2]])],
            }
        ]


def test_only_date_and_clock_fields_use_constrained_predictor() -> None:
    general = FakePredictor("general")
    constrained = FakePredictor("constrained")
    recognizer = ConstrainedPaddleOCRRecognizer(
        general_model=general, constrained_model=constrained
    )
    assert isinstance(recognizer, Recognizer)
    image = np.zeros((4, 4, 3), dtype=np.uint8)

    for field_name in ("date", "start_time", "close_time"):
        assert recognizer.recognize(image, field_name=field_name)[0] == "constrained"
    assert recognizer.recognize(image, field_name="total_time")[0] == "general"
    assert recognizer.recognize(image)[0] == "general"
    assert constrained.calls == 3
    assert general.calls == 2
    assert isinstance(
        constrained.paddlex_pipeline._pipeline.text_rec_model.post_op,
        ConstrainedCTCDecode,
    )
