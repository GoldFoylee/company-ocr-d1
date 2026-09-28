"""Run a scanned log sheet through the existing extraction stages.

The recognizer is supplied through the shared protocol (app/ocr/base.py), so
this module never imports a concrete OCR backend. Callers now pass
PaddleOCRRecognizer (app/ocr/paddle.py) for real extraction; MockRecognizer
remains available for tests that need deterministic, instant OCR output.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import cv2
from sqlalchemy.orm import Session

from app.cropping import FIELD_NAMES, CroppedCell, crop_cells
from app.grid import GridLines, detect_cells, detect_grid_lines
from app.matching import NameMatch, find_best_name_match
from app.models import Extraction, Sheet
from app.ocr.base import FieldAwareRecognizer, Recognizer
from app.preprocessing import preprocess
from app.validation.canonicalization import canonicalize
from app.validation.engine import ExtractedRowValues, ValidationEngine, ValidationResult
from app.validation.flagging import decide_field_flag
from app.validation.scoping import scope_sheet

_REQUIRED_FIELDS = frozenset(field for field in FIELD_NAMES if field != "guest_name")


@dataclass(frozen=True)
class PipelineResult:
    """Persisted sheet identity and the observable outputs of one run."""

    sheet_id: int
    row_count: int
    extraction_count: int
    grid_lines: GridLines
    validation_results: tuple[ValidationResult, ...]
    roster_match: NameMatch | None


@dataclass(frozen=True)
class _RecognizedCrop:
    crop: CroppedCell
    text: str
    confidence: float
    path: Path


def _build_validation_row(fields: dict[str, _RecognizedCrop]) -> ExtractedRowValues:
    """Adapt tagged OCR output to the validation engine's existing row contract."""
    return ExtractedRowValues(
        ds_no=fields["ds_no"].text,
        date=fields["date"].text,
        starting_km=fields["start_km"].text,
        closing_km=fields["close_km"].text,
        total_km=fields["total_km"].text,
        start_time=fields["start_time"].text,
        closing_time=fields["close_time"].text,
        total_time=fields["total_time"].text,
    )


def _normalize_validation_row(row: ExtractedRowValues) -> ExtractedRowValues:
    """Feed the legacy aggregate summary the same supported formats as scoping."""

    def normalized(field: str, raw: str) -> str:
        value = canonicalize(field, raw)
        if value is None:
            return raw
        return value.lower() if field == "total_time" else value

    return ExtractedRowValues(
        ds_no=row.ds_no,
        date=normalized("date", row.date),
        starting_km=normalized("start_km", row.starting_km),
        closing_km=normalized("close_km", row.closing_km),
        total_km=normalized("total_km", row.total_km),
        start_time=normalized("start_time", row.start_time),
        closing_time=normalized("close_time", row.closing_time),
        total_time=normalized("total_time", row.total_time),
    )


def run_sheet_pipeline(
    *,
    image_path: Path,
    crop_root: Path,
    db: Session,
    recognizer: Recognizer,
    vehicle: str,
    branch: str,
    sheet_date: date,
    roster_query: str,
    roster_names: Iterable[str],
) -> PipelineResult:
    """Extract one scanned sheet and commit its audit records.

    ``roster_query`` and ``roster_names`` are caller supplied, synthetic
    demonstration inputs. They never come from the excluded guest-name crop.
    Human correction fields remain NULL until review actually occurs.
    """
    source = image_path.resolve()
    image = cv2.imread(str(source))
    if image is None:
        raise ValueError(f"Could not read sheet image: {source}")

    prepared = preprocess(image)
    grid_lines = detect_grid_lines(prepared)
    cells = detect_cells(prepared)
    if not cells:
        raise ValueError(f"No cells detected in sheet image: {source}")
    crops = crop_cells(prepared, cells)
    if not crops:
        raise ValueError(f"No populated rows detected in sheet image: {source}")

    sheet = Sheet(
        vehicle=vehicle,
        branch=branch,
        date=sheet_date,
        image_path=str(source),
        status="pending",
    )
    sheet_directory: Path | None = None
    created_directory = False
    written_paths: list[Path] = []
    try:
        db.add(sheet)
        db.flush()
        sheet_directory = crop_root.resolve() / f"sheet_{sheet.id:06d}"
        sheet_directory.mkdir(parents=True, exist_ok=False)
        created_directory = True

        recognized_by_row: dict[int, dict[str, _RecognizedCrop]] = {}
        for crop in crops:
            if crop.excluded:
                continue
            path = sheet_directory / f"row{crop.row + 1:02d}_{crop.field_name}.jpg"
            written_paths.append(path)
            if not cv2.imwrite(str(path), crop.image):
                raise OSError(f"Could not write cell image: {path}")
            if isinstance(recognizer, FieldAwareRecognizer):
                text, confidence = recognizer.recognize_field(crop.field_name, crop.image)
            else:
                text, confidence = recognizer.recognize(crop.image)
            row_fields = recognized_by_row.setdefault(crop.row, {})
            if crop.field_name in row_fields:
                raise ValueError(f"Duplicate {crop.field_name} crop in row {crop.row + 1}")
            row_fields[crop.field_name] = _RecognizedCrop(crop, text, confidence, path)

        ordered_rows = sorted(recognized_by_row)
        if len(ordered_rows) != len({crop.row for crop in crops}):
            raise ValueError("A populated row has no eligible crops")
        for row in ordered_rows:
            missing = _REQUIRED_FIELDS - recognized_by_row[row].keys()
            if missing:
                raise ValueError(f"Row {row + 1} has missing field crops: {sorted(missing)}")

        values = [_build_validation_row(recognized_by_row[row]) for row in ordered_rows]
        validation_results = ValidationEngine().validate_sheet(
            [_normalize_validation_row(row) for row in values]
        )
        scoped = scope_sheet(
            values,
            [
                {field: recognized_by_row[row][field].text for field in ("toll", "parking")}
                for row in ordered_rows
            ],
        )

        # This demonstration input is independent of the scanned sheet.
        roster_match = find_best_name_match(roster_query, roster_names)

        extraction_count = 0
        any_flagged = bool(scoped.row_warnings)
        for row_number, row in enumerate(ordered_rows, start=1):
            for recognized in recognized_by_row[row].values():
                decision = decide_field_flag(
                    recognized.text,
                    recognized.confidence,
                    scoped.for_field(row_number, recognized.crop.field_name),
                )
                db.add(
                    Extraction(
                        sheet_id=sheet.id,
                        row_number=recognized.crop.row + 1,
                        field_name=recognized.crop.field_name,
                        image_crop_ref=str(recognized.path),
                        raw_ocr_value=recognized.text,
                        confidence=recognized.confidence,
                        rule_flag=decision.rule_flag,
                        rule_flag_reason=decision.rule_flag_reason,
                        final_value=None,
                        reviewer_id=None,
                        reviewed_at=None,
                    )
                )
                extraction_count += 1
                any_flagged |= decision.rule_flag

        if any_flagged:
            sheet.status = "review"
        db.commit()
        return PipelineResult(
            sheet_id=sheet.id,
            row_count=len(ordered_rows),
            extraction_count=extraction_count,
            grid_lines=grid_lines,
            validation_results=validation_results,
            roster_match=roster_match,
        )
    except Exception:
        db.rollback()
        for path in written_paths:
            path.unlink(missing_ok=True)
        if created_directory and sheet_directory is not None:
            sheet_directory.rmdir()
        raise
