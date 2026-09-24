"""MANUAL measurement: real PP-OCRv6 accuracy against the real golden fixtures.

Not part of the standard suite. Skipped unless OCR_BASELINE=1 is set -- it loads
the real PP-OCRv6 model (downloading weights on first use) and runs it against
all 5 real golden fixtures, which takes minutes, not seconds. Run it explicitly:

    OCR_BASELINE=1 pytest tests/integration/test_paddleocr_baseline.py -s -m manual

This is a MEASUREMENT, not a pass/fail check. Do not add an accuracy assertion
to this file -- see Task C1 in IMPLEMENTATION_PLAN.md: "this one is a
measurement, not pass/fail ... That number is what TrOCR (and later
fine-tuning) gets compared against, so it must be honest, not massaged." The
recorded result lives at docs/baselines/ppocrv6-baseline.md, honestly
including sheet_005's known-illegible journey_details -- see
tests/support/baseline_scoring.py for how buckets and metrics are computed.
"""

import json
import os
import time
from pathlib import Path

import cv2
import pytest

from app.cropping import FIELD_NAMES, CroppedCell, crop_cells
from app.grid import detect_cells
from app.ocr.paddle import PaddleOCRRecognizer
from app.preprocessing import preprocess
from tests.support.baseline_report import RunMetadata, render_json_records, render_markdown_report
from tests.support.baseline_scoring import ScoredCrop, bucket_counts, build_scored_crop

FIXTURE_DIRECTORY = Path("tests/fixtures/anonymized")
FIXTURE_IDS = tuple(f"sheet_{number:03d}" for number in range(1, 6))
REPORT_MARKDOWN_PATH = Path("docs/baselines/ppocrv6-baseline.md")
REPORT_JSON_PATH = Path("docs/baselines/ppocrv6-baseline.json")


def _ocr_baseline_enabled() -> bool:
    return os.environ.get("OCR_BASELINE") == "1"


def _load_ground_truth_rows(sheet_id: str) -> list[dict]:
    payload = json.loads((FIXTURE_DIRECTORY / f"{sheet_id}.json").read_text())
    return payload["rows"]


def _crop_sheet(sheet_id: str) -> tuple[list[CroppedCell], list[dict]]:
    image = cv2.imread(str(FIXTURE_DIRECTORY / f"{sheet_id}.jpg"))
    assert image is not None, f"failed to read fixture image for {sheet_id}"
    preprocessed = preprocess(image)
    cells = detect_cells(preprocessed)
    crops = crop_cells(preprocessed, cells)
    return crops, _load_ground_truth_rows(sheet_id)


def _score_sheet(
    sheet_id: str,
    recognizer: PaddleOCRRecognizer,
    ocr_cache: dict[tuple[str, int, int], tuple[str, float, float]],
) -> list[ScoredCrop]:
    """Score one sheet's crops, reusing one OCR call for toll+parking's shared cell.

    app/cropping/cells.py tags a single physical "Toll Parking" crop with both
    logical field names -- ocr_cache, keyed by (sheet, row, physical column),
    makes sure that shared cell is recognized once, not twice.
    """
    crops, ground_truth_rows = _crop_sheet(sheet_id)
    records: list[ScoredCrop] = []

    for crop in crops:
        ground_truth_value = ground_truth_rows[crop.row].get(crop.field_name)

        if crop.excluded:
            records.append(
                build_scored_crop(
                    sheet_id=sheet_id,
                    row=crop.row,
                    field_name=crop.field_name,
                    ground_truth_value=ground_truth_value,
                    ocr_text=None,
                    confidence=None,
                    elapsed_ms=None,
                )
            )
            continue

        cache_key = (sheet_id, crop.row, crop.column)
        if cache_key not in ocr_cache:
            started_at = time.perf_counter()
            text, confidence = recognizer.recognize(crop.image)
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            ocr_cache[cache_key] = (text, confidence, elapsed_ms)
        text, confidence, elapsed_ms = ocr_cache[cache_key]

        records.append(
            build_scored_crop(
                sheet_id=sheet_id,
                row=crop.row,
                field_name=crop.field_name,
                ground_truth_value=ground_truth_value,
                ocr_text=text,
                confidence=confidence,
                elapsed_ms=elapsed_ms,
            )
        )

    return records


def _run_metadata(model_tier: str, total_wall_clock_seconds: float) -> RunMetadata:
    import paddle
    import paddleocr

    return RunMetadata(
        model_tier=model_tier,
        paddleocr_version=paddleocr.__version__,
        paddlepaddle_version=paddle.__version__,
        device=paddle.device.get_device(),
        total_wall_clock_seconds=total_wall_clock_seconds,
    )


pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        not _ocr_baseline_enabled(),
        reason="set OCR_BASELINE=1 to run the real PP-OCRv6 baseline (slow; downloads model "
        "weights on first use)",
    ),
]


def test_paddleocr_baseline_against_real_golden_fixtures() -> None:
    """Run real PP-OCRv6 against all 5 real golden fixtures and record the result.

    Structural assertions only below -- every crop produced a record, and bucket
    counts reconcile to the total. There is deliberately no accuracy assertion:
    see this module's docstring for why.
    """
    recognizer = PaddleOCRRecognizer()
    ocr_cache: dict[tuple[str, int, int], tuple[str, float, float]] = {}
    all_records: list[ScoredCrop] = []

    started_at = time.perf_counter()
    for sheet_id in FIXTURE_IDS:
        all_records.extend(_score_sheet(sheet_id, recognizer, ocr_cache))
    total_elapsed = time.perf_counter() - started_at

    expected_row_count = sum(len(_load_ground_truth_rows(sheet_id)) for sheet_id in FIXTURE_IDS)
    assert len(all_records) == expected_row_count * len(FIELD_NAMES)
    assert sum(bucket_counts(all_records).values()) == len(all_records)

    metadata = _run_metadata(model_tier="medium", total_wall_clock_seconds=total_elapsed)
    markdown_report = render_markdown_report(all_records, metadata)

    REPORT_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MARKDOWN_PATH.write_text(markdown_report)
    REPORT_JSON_PATH.write_text(render_json_records(all_records))

    print(f"\nBaseline report written to {REPORT_MARKDOWN_PATH} and {REPORT_JSON_PATH}\n")
    print(markdown_report)
