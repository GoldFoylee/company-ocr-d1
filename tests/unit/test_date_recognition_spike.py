"""Guard the provenance and gate of the non-production recovery experiment."""

import numpy as np

from scripts import investigate_date_recognition as spike
from tests.support.baseline_scoring import build_scored_crop


def _date_record(row: int, raw: str, truth: str) -> dict:
    return build_scored_crop(
        sheet_id="sheet_001",
        row=row,
        field_name="date",
        ground_truth_value=truth,
        ocr_text=raw,
        confidence=0.75,
        elapsed_ms=5.0,
    ).as_json_dict()


def test_clahe_preserves_crop_shape_and_does_not_edit_source() -> None:
    original = np.full((40, 80, 3), 180, dtype=np.uint8)
    original[10:20, 30:32] = 140
    copy = original.copy()
    enhanced = spike._clahe_crop(original)
    assert enhanced.shape == original.shape
    assert enhanced.dtype == original.dtype
    assert np.array_equal(original, copy)


def test_recovery_requires_two_consistent_anchors_and_keeps_raw_provenance(monkeypatch) -> None:
    original = [
        _date_record(0, "1/8/26", "2026-08-01"),
        _date_record(1, "21826", "2026-08-02"),
        _date_record(2, "3/8/26", "2026-08-03"),
    ]
    ds = {("sheet_001", i): {"text": str(i + 1), "confidence": 0.9} for i in range(3)}
    monkeypatch.setattr(spike, "_ds_reads", lambda: (ds, 1.0))

    effective, metadata = spike._recovery(original)

    assert effective[1]["ocr_text"] == "21826"
    assert effective[1]["effective_value"] == "2026-08-02"
    assert effective[1]["canonical_exact"] is False
    assert effective[1]["effective_canonical_exact"] is True
    assert effective[1]["confidence"] == 0.75
    assert metadata["provenance"][0]["raw_ocr_text"] == "21826"
    assert metadata["provenance"][0]["raw_ocr_confidence"] == 0.75
    assert metadata["provenance"][0]["reconstructed_confidence"] is None

    # A date gap of three days across two rows does not justify a daily inference.
    invalid = [original[0], original[1], _date_record(2, "4/8/26", "2026-08-04")]
    unchanged, metadata = spike._recovery(invalid)
    assert unchanged == invalid
    assert metadata["effective_value_records"] == 0
