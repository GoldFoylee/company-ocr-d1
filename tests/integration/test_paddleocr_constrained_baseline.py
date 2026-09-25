"""Manual, directly comparable five-fixture measurement of constrained CTC OCR.

The crop path, exclusion buckets, scoring, and report renderer are imported
from the original PP-OCRv6 baseline. Only the recognizer and output paths differ.
Run with OCR_CONSTRAINED_BASELINE=1 pytest -m manual -s \
tests/integration/test_paddleocr_constrained_baseline.py.
"""

import json
import os
import time
from pathlib import Path
from statistics import mean

import pytest

from app.ocr.constrained import ConstrainedPaddleOCRRecognizer
from tests.integration.test_paddleocr_baseline import (
    BASELINE_FIELD_NAMES,
    FIXTURE_IDS,
    _load_ground_truth_rows,
    _run_metadata,
    _score_sheet,
)
from tests.support.baseline_report import render_json_records, render_markdown_report
from tests.support.baseline_scoring import ScoredCrop, bucket_counts

REPORT_MARKDOWN_PATH = Path("docs/baselines/ppocrv6-constrained-baseline.md")
REPORT_JSON_PATH = Path("docs/baselines/ppocrv6-constrained-baseline.json")
ORIGINAL_JSON_PATH = Path("docs/baselines/ppocrv6-baseline.json")
COMPARED_FIELDS = ("date", "start_time", "close_time")

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        os.environ.get("OCR_CONSTRAINED_BASELINE") != "1",
        reason="set OCR_CONSTRAINED_BASELINE=1 to run the real constrained PP-OCRv6 baseline",
    ),
]


def _comparison_table(constrained_records: list[ScoredCrop]) -> str:
    """Compare original and constrained results using stored scorer outputs only."""
    original = json.loads(ORIGINAL_JSON_PATH.read_text())
    constrained = [record.as_json_dict() for record in constrained_records]
    lines = [
        "## Before/after on identical scored crops",
        "",
        "| Field | Scored | canonical_exact original | constrained | change | "
        "char_similarity original | constrained | change |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    confidence_changes: list[str] = []
    for field_name in COMPARED_FIELDS:
        old = [
            row
            for row in original
            if row["field_name"] == field_name and row["bucket"] == "scored"
        ]
        new = [
            row
            for row in constrained
            if row["field_name"] == field_name and row["bucket"] == "scored"
        ]
        assert len(old) == len(new) and len(old) > 0
        assert [(row["sheet_id"], row["row"]) for row in old] == [
            (row["sheet_id"], row["row"]) for row in new
        ]
        old_canonical = mean(float(row["canonical_exact"]) for row in old)
        new_canonical = mean(float(row["canonical_exact"]) for row in new)
        old_similarity = mean(row["char_similarity"] for row in old)
        new_similarity = mean(row["char_similarity"] for row in new)
        old_confidence = mean(row["confidence"] for row in old)
        new_confidence = mean(row["confidence"] for row in new)
        lines.append(
            f"| {field_name} | {len(old)} | {old_canonical:.1%} | {new_canonical:.1%} "
            f"| {(new_canonical - old_canonical) * 100:+.1f} pp "
            f"| {old_similarity:.3f} | {new_similarity:.3f} "
            f"| {new_similarity - old_similarity:+.3f} |"
        )
        confidence_changes.append(f"{field_name} {old_confidence:.3f} → {new_confidence:.3f}")
    lines.extend(
        [
            "",
            "Mean OCR confidence also changed: " + "; ".join(confidence_changes) + ". "
            "Confidence affects review flagging in the sheet pipeline.",
            "",
            "`char_similarity` compares the raw OCR text with normalized ground truth "
            "(for example, a handwritten date with an ISO date), so it is diagnostic "
            "rather than a date parse score.",
            "",
            "## Decoder method and limitation",
            "",
            "The PP-OCRv6 medium model keeps its trained character dictionary. PaddleOCR "
            "3.x binds output indices to that dictionary; replacing it at inference "
            "would mislabel predictions. This run masks all CTC classes except blank, "
            "digits, and `/:-.|` before PaddleX's original CTC decoder chooses classes. "
            "The mask applies only to date and clock fields; no text correction is "
            "performed after recognition. Both `|`/`/` and `1` remain allowed, so a "
            "character-only mask cannot force a separator where the model favors `1`. "
            "Visual inspection of the anonymized crops shows near-vertical separator "
            "strokes; the JSON alone does not establish a literal slash substitution.",
            "",
            "The raw date readings `718126` (sheet_001 row 6), `1618126` "
            "(sheet_003 row 0), `0218126` (sheet_004 row 1), and `118126` "
            "(sheet_005 row 0) remained unchanged by the mask.",
            "",
            "Implementation basis: [PP-OCRv6 model configuration]"
            "(https://github.com/PaddlePaddle/PaddleOCR/blob/main/configs/rec/PP-OCRv6/"
            "PP-OCRv6_medium_rec.yml), [PaddleOCR maintainer guidance]"
            "(https://github.com/PaddlePaddle/PaddleOCR/discussions/17635), and "
            "[PaddleX 3.7 CTC decoder]"
            "(https://github.com/PaddlePaddle/PaddleX/blob/release/3.7/paddlex/"
            "inference/models/text_recognition/processors.py).",
            "",
        ]
    )
    return "\n".join(lines)


def test_constrained_paddleocr_against_real_golden_fixtures() -> None:
    """Record every crop with no accuracy threshold or altered scoring rule."""
    recognizer = ConstrainedPaddleOCRRecognizer()
    ocr_cache: dict[tuple[str, int, int], tuple[str, float, float]] = {}
    all_records: list[ScoredCrop] = []

    started_at = time.perf_counter()
    for sheet_id in FIXTURE_IDS:
        all_records.extend(_score_sheet(sheet_id, recognizer, ocr_cache))
    total_elapsed = time.perf_counter() - started_at

    expected_row_count = sum(len(_load_ground_truth_rows(sheet_id)) for sheet_id in FIXTURE_IDS)
    assert len(all_records) == expected_row_count * len(BASELINE_FIELD_NAMES)
    assert sum(bucket_counts(all_records).values()) == len(all_records)

    metadata = _run_metadata(model_tier="medium", total_wall_clock_seconds=total_elapsed)
    markdown_report = render_markdown_report(all_records, metadata)
    markdown_report = markdown_report.replace(
        "# PP-OCRv6 baseline: real golden-fixture accuracy",
        "# PP-OCRv6 constrained baseline: real golden-fixture accuracy",
        1,
    )
    markdown_report = markdown_report.replace(
        "# PP-OCRv6 constrained baseline: real golden-fixture accuracy\n\n",
        "# PP-OCRv6 constrained baseline: real golden-fixture accuracy\n\n"
        + _comparison_table(all_records)
        + "\n",
        1,
    )
    markdown_report = markdown_report.replace(
        "This is a measurement, not a pass/fail gate.",
        "Date, start_time, and close_time use a CTC character mask (digits and separators); "
        "all other fields use the original decoder. The same five fixtures, crops, "
        "buckets, and scoring rules as ppocrv6-baseline are used. "
        "This is a measurement, not a pass/fail gate.",
        1,
    )
    REPORT_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MARKDOWN_PATH.write_text(markdown_report)
    REPORT_JSON_PATH.write_text(render_json_records(all_records))

    print(f"\nConstrained report written to {REPORT_MARKDOWN_PATH} and {REPORT_JSON_PATH}\n")
    print(markdown_report)
