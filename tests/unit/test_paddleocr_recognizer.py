"""Contract tests for PaddleOCRRecognizer against a mocked model.

No real PaddleOCR model runs here -- every test supplies a fake predictor via the
`model=` constructor argument. The real-model measurement lives in
tests/integration/test_paddleocr_baseline.py (manual, skipped by default).
"""

import sys

import numpy as np
import pytest

from app.ocr.base import InvalidCellImageError, OCRBackendError, Recognizer
from app.ocr.paddle import PaddleOCRRecognizer

CELL_IMAGE = np.zeros((24, 80, 3), dtype=np.uint8)


class FakePredictor:
    """Stands in for PaddleOCR's `.predict()`, returning canned dict-like results."""

    def __init__(self, results: list[dict] | None = None, exception: Exception | None = None):
        self._results = results if results is not None else []
        self._exception = exception
        self.received_inputs: list[np.ndarray] = []

    def predict(self, input: np.ndarray) -> list[dict]:
        self.received_inputs.append(input)
        if self._exception is not None:
            raise self._exception
        return self._results


def _result(texts: list[str], scores: list[float], polys: list[list[list[int]]]) -> dict:
    return {"rec_texts": texts, "rec_scores": scores, "rec_polys": polys}


def test_paddleocr_recognizer_satisfies_protocol() -> None:
    recognizer = PaddleOCRRecognizer(model=FakePredictor())

    assert isinstance(recognizer, Recognizer)


def test_recognizes_single_line() -> None:
    predictor = FakePredictor(
        results=[_result(["23695"], [0.93], [[[0, 0], [40, 0], [40, 20], [0, 20]]])]
    )
    recognizer = PaddleOCRRecognizer(model=predictor)

    text, confidence = recognizer.recognize(CELL_IMAGE)

    assert (text, confidence) == ("23695", 0.93)
    assert isinstance(text, str)
    assert isinstance(confidence, float)


def test_joins_multiple_lines_in_reading_order_top_to_bottom() -> None:
    # Lines supplied out of reading order; polys place "AM" below "8:00".
    predictor = FakePredictor(
        results=[
            _result(
                texts=["AM", "8:00"],
                scores=[0.80, 0.90],
                polys=[
                    [[0, 20], [30, 20], [30, 40], [0, 40]],  # AM: top=20
                    [[0, 0], [30, 0], [30, 18], [0, 18]],  # 8:00: top=0
                ],
            )
        ]
    )
    recognizer = PaddleOCRRecognizer(model=predictor)

    text, confidence = recognizer.recognize(CELL_IMAGE)

    assert text == "8:00 AM"
    assert confidence == 0.80


def test_orders_same_row_lines_left_to_right() -> None:
    predictor = FakePredictor(
        results=[
            _result(
                texts=["right", "left"],
                scores=[0.7, 0.6],
                polys=[
                    [[50, 0], [80, 0], [80, 10], [50, 10]],  # left=50
                    [[0, 0], [30, 0], [30, 10], [0, 10]],  # left=0
                ],
            )
        ]
    )
    recognizer = PaddleOCRRecognizer(model=predictor)

    text, _ = recognizer.recognize(CELL_IMAGE)

    assert text == "left right"


def test_confidence_is_the_minimum_across_lines() -> None:
    predictor = FakePredictor(
        results=[
            _result(
                texts=["GH+299", "+316+GH"],
                scores=[0.95, 0.42],
                polys=[
                    [[0, 0], [40, 0], [40, 18], [0, 18]],
                    [[0, 20], [40, 20], [40, 38], [0, 38]],
                ],
            )
        ]
    )
    recognizer = PaddleOCRRecognizer(model=predictor)

    _, confidence = recognizer.recognize(CELL_IMAGE)

    assert confidence == 0.42


def test_skips_empty_text_lines() -> None:
    predictor = FakePredictor(
        results=[
            _result(
                texts=["", "23695"],
                scores=[0.99, 0.93],
                polys=[
                    [[0, 0], [10, 0], [10, 5], [0, 5]],
                    [[0, 10], [40, 10], [40, 30], [0, 30]],
                ],
            )
        ]
    )
    recognizer = PaddleOCRRecognizer(model=predictor)

    text, confidence = recognizer.recognize(CELL_IMAGE)

    assert (text, confidence) == ("23695", 0.93)


def test_no_recognized_lines_returns_empty_text_and_zero_confidence() -> None:
    predictor = FakePredictor(results=[_result([], [], [])])
    recognizer = PaddleOCRRecognizer(model=predictor)

    text, confidence = recognizer.recognize(CELL_IMAGE)

    assert (text, confidence) == ("", 0.0)


def test_no_predict_results_returns_empty_text_and_zero_confidence() -> None:
    predictor = FakePredictor(results=[])
    recognizer = PaddleOCRRecognizer(model=predictor)

    text, confidence = recognizer.recognize(CELL_IMAGE)

    assert (text, confidence) == ("", 0.0)


def test_passes_the_cell_image_through_to_the_predictor() -> None:
    predictor = FakePredictor(results=[_result([], [], [])])
    recognizer = PaddleOCRRecognizer(model=predictor)

    recognizer.recognize(CELL_IMAGE)

    assert len(predictor.received_inputs) == 1
    assert predictor.received_inputs[0] is CELL_IMAGE


@pytest.mark.parametrize(
    "cell_image",
    [
        np.empty((0, 0), dtype=np.uint8),
        np.empty((10, 0, 3), dtype=np.uint8),
    ],
)
def test_rejects_empty_images(cell_image: np.ndarray) -> None:
    recognizer = PaddleOCRRecognizer(model=FakePredictor())

    with pytest.raises(InvalidCellImageError, match="must not be empty"):
        recognizer.recognize(cell_image)


@pytest.mark.parametrize(
    "cell_image",
    [
        b"not-an-image",
        np.zeros((10,), dtype=np.uint8),
        np.zeros((10, 10, 2), dtype=np.uint8),
    ],
)
def test_rejects_corrupt_images(cell_image: object) -> None:
    recognizer = PaddleOCRRecognizer(model=FakePredictor())

    with pytest.raises(InvalidCellImageError):
        recognizer.recognize(cell_image)  # type: ignore[arg-type]


def test_invalid_image_is_rejected_before_the_predictor_is_called() -> None:
    predictor = FakePredictor(results=[_result([], [], [])])
    recognizer = PaddleOCRRecognizer(model=predictor)

    with pytest.raises(InvalidCellImageError):
        recognizer.recognize(np.empty((0, 0), dtype=np.uint8))

    assert predictor.received_inputs == []


def test_out_of_range_confidence_raises_value_error() -> None:
    predictor = FakePredictor(
        results=[_result(["23695"], [1.5], [[[0, 0], [40, 0], [40, 20], [0, 20]]])]
    )
    recognizer = PaddleOCRRecognizer(model=predictor)

    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        recognizer.recognize(CELL_IMAGE)


def test_backend_exception_is_wrapped_and_chained() -> None:
    original_error = RuntimeError("model crashed")
    predictor = FakePredictor(exception=original_error)
    recognizer = PaddleOCRRecognizer(model=predictor)

    with pytest.raises(OCRBackendError) as exc_info:
        recognizer.recognize(CELL_IMAGE)

    assert exc_info.value.__cause__ is original_error


def test_importing_app_ocr_does_not_import_paddleocr() -> None:
    assert "paddleocr" not in sys.modules


def test_missing_paddleocr_package_raises_actionable_import_error(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "paddleocr", None)

    with pytest.raises(ImportError, match="paddleocr is not installed"):
        PaddleOCRRecognizer()


# --- enable_mkldnn gating (see app/ocr/paddle.py's _MKLDNN_ENV_VAR comment) ---
#
# These monkeypatch _build_predictor rather than constructing a real PaddleOCR
# model: they verify what gets passed to it, not the real model's behavior.


def _capture_build_predictor_calls(monkeypatch) -> list[bool]:
    calls: list[bool] = []

    def fake_build_predictor(model_tier: str, enable_mkldnn: bool):
        calls.append(enable_mkldnn)
        return FakePredictor()

    monkeypatch.setattr("app.ocr.paddle._build_predictor", fake_build_predictor)
    return calls


def test_enable_mkldnn_defaults_to_enabled_when_env_var_unset(monkeypatch) -> None:
    monkeypatch.delenv("PADDLEOCR_ENABLE_MKLDNN", raising=False)
    calls = _capture_build_predictor_calls(monkeypatch)

    PaddleOCRRecognizer()

    assert calls == [True]


@pytest.mark.parametrize("disabled_value", ["0", "false", "False", "no", "OFF"])
def test_enable_mkldnn_env_var_disables_it(monkeypatch, disabled_value: str) -> None:
    monkeypatch.setenv("PADDLEOCR_ENABLE_MKLDNN", disabled_value)
    calls = _capture_build_predictor_calls(monkeypatch)

    PaddleOCRRecognizer()

    assert calls == [False]


@pytest.mark.parametrize("enabled_value", ["1", "true", "yes", "anything-else"])
def test_enable_mkldnn_env_var_other_values_keep_it_enabled(
    monkeypatch, enabled_value: str
) -> None:
    monkeypatch.setenv("PADDLEOCR_ENABLE_MKLDNN", enabled_value)
    calls = _capture_build_predictor_calls(monkeypatch)

    PaddleOCRRecognizer()

    assert calls == [True]


def test_enable_mkldnn_constructor_override_wins_over_env_var(monkeypatch) -> None:
    monkeypatch.setenv("PADDLEOCR_ENABLE_MKLDNN", "0")
    calls = _capture_build_predictor_calls(monkeypatch)

    PaddleOCRRecognizer(enable_mkldnn=True)

    assert calls == [True]


def test_enable_mkldnn_is_not_consulted_when_model_is_supplied_directly(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("_build_predictor must not run when model= is given")

    monkeypatch.setattr("app.ocr.paddle._build_predictor", fail_if_called)

    recognizer = PaddleOCRRecognizer(model=FakePredictor())

    assert isinstance(recognizer, Recognizer)
