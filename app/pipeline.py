"""Run a scanned log sheet through the existing extraction stages.

The recognizer is supplied through the shared protocol. Until real OCR is
available, callers can pass MockRecognizer without changing this module.
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
from app.ocr.base import Recognizer
from app.preprocessing import preprocess
from app.validation.engine import ExtractedRowValues, ValidationEngine, ValidationResult
from app.validation.flagging import decide_field_flag

_REQUIRED_FIELDS = frozenset(field for field in FIELD_NAMES if field != "guest_name")
_KILOMETRE_FIELDS = frozenset({"start_km", "close_km", "total_km"})
_TIME_FIELDS = frozenset({"start_time", "close_time", "total_time"})


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


def _validation_for_field(
    field_name: str,
    row_number: int,
    row_rules: dict[tuple[str, int], ValidationResult],
    date_rule: ValidationResult,
    ds_rule: ValidationResult,
) -> ValidationResult:
    """Attach each existing rule to the fields that it actually checks."""
    if field_name in _KILOMETRE_FIELDS:
        return row_rules[("kilometre_total", row_number)]
    if field_name in _TIME_FIELDS:
        return row_rules[("time_total", row_number)]
    if field_name == "date":
        return date_rule
    if field_name == "ds_no":
        return ds_rule
    return ValidationResult(
        rule="no_applicable_rule",
        passed=True,
        reason=f"No validation rule applies to {field_name}",
        row_number=row_number,
    )


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
        validation_results = ValidationEngine().validate_sheet(values)
        row_rules = {
            (result.rule, result.row_number): result
            for result in validation_results
            if result.row_number is not None
        }
        date_rule = next(
            result for result in validation_results if result.rule == "non_decreasing_dates"
        )
        ds_rule = next(
            result for result in validation_results if result.rule == "unique_ds_no"
        )

        # This demonstration input is independent of the scanned sheet.
        roster_match = find_best_name_match(roster_query, roster_names)

        extraction_count = 0
        any_flagged = any(not result.passed for result in validation_results)
        for row_number, row in enumerate(ordered_rows, start=1):
            for recognized in recognized_by_row[row].values():
                decision = decide_field_flag(
                    recognized.text,
                    recognized.confidence,
                    _validation_for_field(
                        recognized.crop.field_name, row_number, row_rules, date_rule, ds_rule
                    ),
                )
                db.add(
                    Extraction(
                        sheet_id=sheet.id,
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
