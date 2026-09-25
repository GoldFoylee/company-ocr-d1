"""Reproducible, non-production spikes on the locked five-sheet OCR baseline.

Run in the same Docker image/model environment as the PP-OCRv6 baseline. The
scorer and source fixture geometry are imported, never modified. Only the three
affected fields are rerun; every other record is copied verbatim from the
original 781-record baseline for the structural check. Reports publish only
the 213 affected records, to avoid duplicating unaffected baseline evidence.
"""

import argparse
import json
import re
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import cv2

from app.ocr.paddle import PaddleOCRRecognizer, _build_predictor
from tests.integration.test_paddleocr_baseline import FIXTURE_IDS, _crop_sheet
from tests.support.baseline_scoring import build_scored_crop, canonicalize

BASELINE = Path("docs/baselines/ppocrv6-baseline.json")
OUT_DIR = Path("docs/baselines")
TARGETS = frozenset({"date", "start_time", "close_time"})


def _clahe_crop(image):
    """Local luminance contrast, fixed before measuring all five fixtures."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    luminance, a, b = cv2.split(lab)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(luminance)
    return cv2.cvtColor(cv2.merge((enhanced, a, b)), cv2.COLOR_LAB2BGR)


def _records_with_ocr(variant: str, base: list[dict]) -> tuple[list[dict], dict]:
    if variant == "detector_sensitivity":
        from paddleocr import PaddleOCR

        model = PaddleOCR(
            text_detection_model_name="PP-OCRv6_medium_det",
            text_recognition_model_name="PP-OCRv6_medium_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
            text_det_thresh=0.1,
            text_det_box_thresh=0.3,
        )
        recognizer = PaddleOCRRecognizer(model=model)
    else:
        recognizer = PaddleOCRRecognizer(model=_build_predictor("medium", False))

    by_key = {(r["sheet_id"], r["row"], r["field_name"]): r for r in base}
    fresh = {}
    started = time.perf_counter()
    for sheet_id in FIXTURE_IDS:
        crops, truth_rows = _crop_sheet(sheet_id)
        for crop in crops:
            if crop.field_name not in TARGETS:
                continue
            key = (sheet_id, crop.row, crop.field_name)
            assert key in by_key and not crop.excluded
            image = _clahe_crop(crop.image) if variant == "crop_clahe" else crop.image
            t0 = time.perf_counter()
            if variant == "field_routed":
                text, confidence = recognizer.recognize_field(crop.field_name, image)
            else:
                text, confidence = recognizer.recognize(image)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            fresh[key] = asdict(
                build_scored_crop(
                    sheet_id=sheet_id,
                    row=crop.row,
                    field_name=crop.field_name,
                    ground_truth_value=truth_rows[crop.row].get(crop.field_name),
                    ocr_text=text,
                    confidence=confidence,
                    elapsed_ms=elapsed_ms,
                )
            )
    assert len(fresh) == 213, len(fresh)
    records = [fresh.get((r["sheet_id"], r["row"], r["field_name"]), r) for r in base]
    return records, {
        "variant": variant,
        "elapsed_seconds": time.perf_counter() - started,
        "fresh_target_records": len(fresh),
        "copied_other_records": len(base) - len(fresh),
    }


def _ds_reads() -> tuple[dict[tuple[str, int], dict], float]:
    recognizer = PaddleOCRRecognizer(model=_build_predictor("medium", False))
    reads = {}
    started = time.perf_counter()
    for sheet_id in FIXTURE_IDS:
        crops, _ = _crop_sheet(sheet_id)
        for crop in crops:
            if crop.field_name != "ds_no":
                continue
            text, confidence = recognizer.recognize(crop.image)
            reads[(sheet_id, crop.row)] = {"text": text, "confidence": confidence}
    assert len(reads) == 71
    return reads, time.perf_counter() - started


def _recovery(base: list[dict]) -> tuple[list[dict], dict]:
    """Infer digit-only dates only between two observed date/DS anchors.

    No ground truth is consulted. Both anchors must parse, their OCR DS numbers
    must match row distance, and their dates must differ by that many days.
    All intervening DS reads must be consecutive. The effective value is scored
    separately while the original raw OCR text/confidence stays in provenance.
    """
    ds, seconds = _ds_reads()
    dates = {(r["sheet_id"], r["row"]): r for r in base if r["field_name"] == "date"}
    inferred = {}
    for sheet_id in FIXTURE_IDS:
        rows = sorted(row for sid, row in dates if sid == sheet_id)
        anchors = []
        for row in rows:
            record = dates[sheet_id, row]
            parsed = canonicalize("date", record["ocr_text"] or "")
            ds_text = ds[sheet_id, row]["text"]
            if parsed is not None and re.fullmatch(r"[1-9]\d*", ds_text):
                anchors.append((row, date.fromisoformat(parsed), int(ds_text)))
        for (left_row, left_date, left_ds), (right_row, right_date, right_ds) in zip(
            anchors, anchors[1:], strict=False
        ):
            gap = right_row - left_row
            if gap < 2 or right_ds - left_ds != gap or (right_date - left_date).days != gap:
                continue
            for row in range(left_row + 1, right_row):
                record = dates[sheet_id, row]
                raw = record["ocr_text"] or ""
                expected_ds = left_ds + (row - left_row)
                if not (
                    re.fullmatch(r"\d{5,8}", raw) and ds[sheet_id, row]["text"] == str(expected_ds)
                ):
                    continue
                value = (left_date + timedelta(days=row - left_row)).isoformat()
                inferred[(sheet_id, row)] = {
                    "effective_value": value,
                    "source": "reconstructed_between_ocr_anchors",
                    "raw_ocr_text": raw,
                    "raw_ocr_confidence": record["confidence"],
                    "reconstructed_confidence": None,
                    "left_anchor": {
                        "row": left_row,
                        "raw_date": dates[sheet_id, left_row]["ocr_text"],
                        "raw_ds_no": ds[sheet_id, left_row],
                    },
                    "right_anchor": {
                        "row": right_row,
                        "raw_date": dates[sheet_id, right_row]["ocr_text"],
                        "raw_ds_no": ds[sheet_id, right_row],
                    },
                    "row_ds_no": ds[sheet_id, row],
                }
    records = []
    for record in base:
        info = (
            inferred.get((record["sheet_id"], record["row"]))
            if record["field_name"] == "date"
            else None
        )
        if info is None:
            records.append(record)
            continue
        scored_effective = asdict(
            build_scored_crop(
                sheet_id=record["sheet_id"],
                row=record["row"],
                field_name="date",
                ground_truth_value=record["ground_truth"],
                ocr_text=info["effective_value"],
                confidence=record["confidence"],
                elapsed_ms=record["elapsed_ms"],
            )
        )
        records.append(
            {
                **record,
                "effective_value": info["effective_value"],
                "effective_source": info["source"],
                "effective_raw_exact": scored_effective["raw_exact"],
                "effective_canonical_exact": scored_effective["canonical_exact"],
                "effective_char_similarity": scored_effective["char_similarity"],
                "reconstructed_confidence": None,
            }
        )
    metadata = {
        "variant": "bounded_recovery",
        "elapsed_seconds": seconds,
        "fresh_target_records": 0,
        "copied_other_records": len(base),
        "effective_value_records": len(inferred),
        "provenance": list({"sheet_id": k[0], "row": k[1], **v} for k, v in inferred.items()),
        "ds_reads": [{"sheet_id": k[0], "row": k[1], **v} for k, v in ds.items()],
    }
    return records, metadata


def main():
    import paddle
    import paddleocr

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "variant",
        choices=(
            "control",
            "detector_sensitivity",
            "crop_clahe",
            "bounded_recovery",
            "field_routed",
        ),
    )
    args = parser.parse_args()
    base = json.loads(BASELINE.read_text())
    assert len(base) == 781
    if args.variant == "bounded_recovery":
        records, meta = _recovery(base)
    else:
        records, meta = _records_with_ocr(args.variant, base)
    meta.update(
        {
            "fixture_ids": list(FIXTURE_IDS),
            "source_baseline": str(BASELINE),
            "target_fields": sorted(TARGETS),
            "model": "PP-OCRv6_medium_det + PP-OCRv6_medium_rec",
            "paddleocr_version": paddleocr.__version__,
            "paddlepaddle_version": paddle.__version__,
            "device": paddle.device.get_device(),
            "scorer": "tests/support/baseline_scoring.py (unchanged)",
            "report_scope": "213 date/start_time/close_time records from 781-record comparison",
        }
    )
    assert len(records) == len(base)
    assert [
        (r["sheet_id"], r["row"], r["field_name"], r["bucket"], r["ground_truth"]) for r in records
    ] == [(r["sheet_id"], r["row"], r["field_name"], r["bucket"], r["ground_truth"]) for r in base]
    path = OUT_DIR / f"date-recognition-{args.variant}.json"
    target_records = [r for r in records if r["field_name"] in TARGETS]
    assert len(target_records) == 213
    rendered = (
        "{\n  \"metadata\": "
        + json.dumps(meta, indent=2, sort_keys=True).replace("\n", "\n  ")
        + ',\n  "records": [\n'
        + ",\n".join("    " + json.dumps(r, sort_keys=True) for r in target_records)
        + "\n  ]\n}\n"
    )
    path.write_text(rendered)
    print(path, meta["elapsed_seconds"])
    for field in sorted(TARGETS):
        for name, dataset in (("before", base), ("after", records)):
            selected = [r for r in dataset if r["field_name"] == field and r["bucket"] == "scored"]
            prefix = "effective_" if args.variant == "bounded_recovery" and name == "after" else ""
            print(
                args.variant,
                field,
                name,
                sum(
                    bool(r.get(prefix + "canonical_exact", r["canonical_exact"])) for r in selected
                ),
                round(
                    sum(r.get(prefix + "char_similarity", r["char_similarity"]) for r in selected)
                    / len(selected),
                    4,
                ),
                round(sum(r["confidence"] for r in selected) / len(selected), 4),
            )


if __name__ == "__main__":
    main()
