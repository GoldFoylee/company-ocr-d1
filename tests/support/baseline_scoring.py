"""Scoring and report rendering for the PP-OCRv6 real-fixture baseline measurement.

This is a measurement harness, not a pass/fail gate: nothing here asserts an
accuracy threshold. See tests/integration/test_paddleocr_baseline.py for how it is
used, and docs/baselines/ppocrv6-baseline.md for the recorded result.

Three metrics are computed per scored field, never just one -- see the module
docstring on `canonicalize()` for why a single "accuracy" number would be
misleading here, given that ground truth is stored in a normalized form the
source sheet does not use.
"""

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Final, Literal

from rapidfuzz.distance import Levenshtein

Bucket = Literal["scored", "redacted", "no_ground_truth"]

# Fields excluded from OCR entirely: the crop is a black redaction box (see
# tests/fixtures/anonymized/README.md). Never scored, never even recognized.
_REDACTED_FIELD_NAMES: Final[frozenset[str]] = frozenset({"guest_name"})


# --- Canonicalization ------------------------------------------------------
#
# Ground truth is stored in a normalized form the sheet itself does not use (an
# ISO date vs. "1|8|26" as written, a 24-hour time vs. two handwritten lines, a
# categorical total_time vs. a bare number). A raw string-equality match would
# read close to 0% for these fields regardless of whether PP-OCRv6 read the
# handwriting correctly -- that would measure the ground-truth schema, not the
# model. So `canonical_exact` exists alongside `raw_exact`, not instead of it.
#
# Each canonicalizer is applied identically to both sides of the comparison (the
# OCR text and the ground-truth string) -- the same function tries the same
# fixed list of formats against whichever text it is given, so which side is
# "the sheet's format" and which is "the ground truth's format" is not hardcoded
# into the function. Mirrors the fixed-format-list pattern already used by
# app/validation/engine.py's own date parsing (_DATE_FORMATS).
#
# These rules are fixed before the baseline is first run and are not to be
# edited after seeing a result -- see docs/baselines/ppocrv6-baseline.md's own
# statement of that guardrail.

_DATE_INPUT_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%d|%m|%Y",
    "%d|%m|%y",
)

_TIME_INPUT_FORMATS: Final[tuple[str, ...]] = (
    "%H:%M",
    "%I:%M %p",
    "%I:%M%p",
    "%I.%M %p",
)

# The form's own convention: a bare duration number means hours; "day"/"1D"
# variants mean a full day. See app/validation/engine.py's TOTAL_TIME_CATEGORIES
# for the canonical category set this maps onto.
_TOTAL_TIME_ALIASES: Final[dict[str, str]] = {
    "0": "0H",
    "0H": "0H",
    "12": "12H",
    "12H": "12H",
    "1D": "1D",
    "1DAY": "1D",
    "DAY": "1D",
}

_WHITESPACE_RE: Final = re.compile(r"\s+")
_NON_DIGIT_RE: Final = re.compile(r"[^\d]")
_NON_ALNUM_RE: Final = re.compile(r"[^A-Z0-9]")


def _normalize_universal(value: str) -> str:
    """Default canonicalization: collapse whitespace, uppercase. No parsing."""
    return _WHITESPACE_RE.sub(" ", value.strip()).upper()


def _canonical_date(value: str) -> str | None:
    stripped = value.strip()
    for fmt in _DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(stripped, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _canonical_time(value: str) -> str | None:
    normalized = _WHITESPACE_RE.sub(" ", value.strip().upper())
    for fmt in _TIME_INPUT_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def _canonical_km(value: str) -> str | None:
    digits = _NON_DIGIT_RE.sub("", value)
    if not digits:
        return None
    return str(int(digits))


def _canonical_total_time(value: str) -> str | None:
    normalized = _NON_ALNUM_RE.sub("", value.strip().upper())
    return _TOTAL_TIME_ALIASES.get(normalized)


def _canonical_toll_or_parking(value: str) -> str:
    # The form's convention: a blank Toll/Parking cell means nothing was paid.
    digits = _NON_DIGIT_RE.sub("", value.strip())
    return digits if digits else "0"


_CANONICALIZERS: Final[dict[str, Callable[[str], str | None]]] = {
    "date": _canonical_date,
    "start_time": _canonical_time,
    "close_time": _canonical_time,
    "start_km": _canonical_km,
    "close_km": _canonical_km,
    "total_km": _canonical_km,
    "total_time": _canonical_total_time,
    "toll": _canonical_toll_or_parking,
    "parking": _canonical_toll_or_parking,
}


def canonicalize(field_name: str, value: str) -> str | None:
    """Map raw text to this field's canonical form, or None if it doesn't parse."""
    canonicalizer = _CANONICALIZERS.get(field_name, _normalize_universal)
    return canonicalizer(value)


# --- Metrics -----------------------------------------------------------------


def raw_exact(ocr_text: str, ground_truth: str) -> bool:
    """Verbatim string equality. No transformation. Always the headline number."""
    return ocr_text == ground_truth


def canonical_exact(field_name: str, ocr_text: str, ground_truth: str) -> bool:
    """Exact match after canonicalize() on both sides. Unparseable => no match."""
    left = canonicalize(field_name, ocr_text)
    right = canonicalize(field_name, ground_truth)
    if left is None or right is None:
        return False
    return left == right


def char_similarity(ocr_text: str, ground_truth: str) -> float:
    """Continuous character-level similarity in [0.0, 1.0]. A diagnostic, not a match."""
    return Levenshtein.normalized_similarity(ocr_text, ground_truth)


def bucket_for(field_name: str, ground_truth_value: object) -> Bucket:
    """Classify a tagged field crop before any OCR result exists.

    "guest_name" is never scored (or even recognized -- the crop is a redaction).
    A missing ground-truth value (None or "") means the source was illegible to
    the human transcriber, per tests/fixtures/anonymized -- excluded from scoring,
    but not hidden: see no_ground_truth_records().
    """
    if field_name in _REDACTED_FIELD_NAMES:
        return "redacted"
    if ground_truth_value is None or ground_truth_value == "":
        return "no_ground_truth"
    return "scored"


# --- Records -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScoredCrop:
    """One tagged field crop's OCR result and, where applicable, its scoring."""

    sheet_id: str
    row: int
    field_name: str
    bucket: Bucket
    ground_truth: str | None
    ocr_text: str | None
    confidence: float | None
    elapsed_ms: float | None
    raw_exact: bool | None
    canonical_exact: bool | None
    char_similarity: float | None

    def as_json_dict(self) -> dict:
        return asdict(self)


def build_scored_crop(
    *,
    sheet_id: str,
    row: int,
    field_name: str,
    ground_truth_value: object,
    ocr_text: str | None,
    confidence: float | None,
    elapsed_ms: float | None,
) -> ScoredCrop:
    """Build one record, scoring it only when its bucket is "scored"."""
    bucket = bucket_for(field_name, ground_truth_value)
    ground_truth_str = None if ground_truth_value is None else str(ground_truth_value)

    if bucket != "scored" or ocr_text is None:
        return ScoredCrop(
            sheet_id=sheet_id,
            row=row,
            field_name=field_name,
            bucket=bucket,
            ground_truth=ground_truth_str,
            ocr_text=ocr_text,
            confidence=confidence,
            elapsed_ms=elapsed_ms,
            raw_exact=None,
            canonical_exact=None,
            char_similarity=None,
        )

    assert ground_truth_str is not None  # bucket == "scored" guarantees this
    return ScoredCrop(
        sheet_id=sheet_id,
        row=row,
        field_name=field_name,
        bucket=bucket,
        ground_truth=ground_truth_str,
        ocr_text=ocr_text,
        confidence=confidence,
        elapsed_ms=elapsed_ms,
        raw_exact=raw_exact(ocr_text, ground_truth_str),
        canonical_exact=canonical_exact(field_name, ocr_text, ground_truth_str),
        char_similarity=char_similarity(ocr_text, ground_truth_str),
    )


# --- Summaries ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldSummary:
    """Aggregate metrics for one field, over one sheet or over all sheets."""

    field_name: str
    scored_count: int
    raw_exact_count: int
    canonical_exact_count: int
    mean_char_similarity: float
    mean_confidence: float

    @property
    def raw_exact_rate(self) -> float:
        return self.raw_exact_count / self.scored_count if self.scored_count else 0.0

    @property
    def canonical_exact_rate(self) -> float:
        return self.canonical_exact_count / self.scored_count if self.scored_count else 0.0


def summarize_field(field_name: str, records: list[ScoredCrop]) -> FieldSummary:
    scored = [r for r in records if r.field_name == field_name and r.bucket == "scored"]
    count = len(scored)
    if count == 0:
        return FieldSummary(field_name, 0, 0, 0, 0.0, 0.0)
    return FieldSummary(
        field_name=field_name,
        scored_count=count,
        raw_exact_count=sum(1 for r in scored if r.raw_exact),
        canonical_exact_count=sum(1 for r in scored if r.canonical_exact),
        mean_char_similarity=sum(r.char_similarity or 0.0 for r in scored) / count,
        mean_confidence=sum(r.confidence or 0.0 for r in scored) / count,
    )


def bucket_counts(records: list[ScoredCrop]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.bucket] = counts.get(record.bucket, 0) + 1
    return counts


def no_ground_truth_records(records: list[ScoredCrop]) -> list[ScoredCrop]:
    """Records excluded from scoring for lack of ground truth, sorted for display.

    Includes sheet_005's 15 journey_details rows (illegible to the human
    transcriber -- see tests/fixtures/anonymized/sheet_005.json) and any other
    row whose ground truth is empty, e.g. sheet_004's one blank journey_details.
    """
    matches = [r for r in records if r.bucket == "no_ground_truth"]
    return sorted(matches, key=lambda r: (r.sheet_id, r.field_name, r.row))
