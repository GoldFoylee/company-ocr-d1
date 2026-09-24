"""Render the PP-OCRv6 baseline measurement as Markdown and JSON.

Rendering only -- see tests/support/baseline_scoring.py for the metrics and
bucket rules this reads, and tests/integration/test_paddleocr_baseline.py for
where the numbers actually come from.
"""

import json
from dataclasses import dataclass
from typing import Final

from tests.support.baseline_scoring import (
    FieldSummary,
    ScoredCrop,
    bucket_counts,
    no_ground_truth_records,
    summarize_field,
)

# Fixed reporting order: matches app/cropping/cells.py's FIELD_NAMES, excluding
# guest_name (never scored -- see baseline_scoring._REDACTED_FIELD_NAMES).
SCORED_FIELD_NAMES: Final[tuple[str, ...]] = (
    "date",
    "start_time",
    "start_km",
    "close_time",
    "close_km",
    "total_km",
    "total_time",
    "toll",
    "parking",
    "journey_details",
)

_BUCKET_REASONS: Final[dict[str, str]] = {
    "redacted": "guest_name crop is a black redaction box; OCR is never run on it",
    "no_ground_truth": "ground truth is empty -- illegible to the human transcriber",
}

_CANONICALIZATION_RULES_TEXT: Final = """\
Canonicalization rules (fixed before this baseline was first run; see
tests/support/baseline_scoring.py for the implementation):

- All fields: strip surrounding whitespace, collapse internal whitespace, uppercase.
- `date`: parsed against `%Y-%m-%d`, `%d/%m/%Y`, `%d/%m/%y`, `%d-%m-%Y`, `%d-%m-%y`,
  `%d.%m.%Y`, `%d.%m.%y`, `%d|%m|%Y`, `%d|%m|%y` (first match wins); unparseable => no match.
- `start_time` / `close_time`: parsed against `%H:%M`, `%I:%M %p`, `%I:%M%p`, `%I.%M %p`;
  unparseable => no match.
- `start_km` / `close_km` / `total_km`: non-digit characters stripped, compared as integers.
- `total_time`: bare `12` => `12H` (a 12-hour duty, the form's own convention);
  `0`/`0H` => `0H`; `1D`/`1DAY`/`DAY` => `1D`; anything else => no match.
- `toll` / `parking`: a blank cell => `0` (the form's convention: blank means nothing paid);
  otherwise non-digit characters are stripped.

No rule was added or changed after seeing a result. `raw_exact` (verbatim string equality,
no transformation at all) is always the headline number -- `canonical_exact` is a second,
clearly-labelled number alongside it, not a replacement for it.
"""


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """Facts about how the baseline was produced, recorded alongside the numbers."""

    model_tier: str
    paddleocr_version: str
    paddlepaddle_version: str
    device: str
    total_wall_clock_seconds: float


def _fmt_pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _field_summary_row(summary: FieldSummary) -> str:
    if summary.scored_count == 0:
        return f"| {summary.field_name} | 0 | -- | -- | -- | -- |"
    return (
        f"| {summary.field_name} | {summary.scored_count} "
        f"| {_fmt_pct(summary.raw_exact_rate)} | {_fmt_pct(summary.canonical_exact_rate)} "
        f"| {summary.mean_char_similarity:.3f} | {summary.mean_confidence:.3f} |"
    )


def _render_field_table(title: str, records: list[ScoredCrop]) -> str:
    lines = [
        f"### {title}",
        "",
        "| Field | Scored | raw_exact | canonical_exact | mean char_similarity"
        " | mean confidence |",
        "|---|---|---|---|---|---|",
    ]
    for field_name in SCORED_FIELD_NAMES:
        lines.append(_field_summary_row(summarize_field(field_name, records)))
    lines.append("")
    return "\n".join(lines)


def _render_bucket_counts(records: list[ScoredCrop]) -> str:
    counts = bucket_counts(records)
    lines = ["### Excluded from scoring", ""]
    lines.append(f"- **scored**: {counts.get('scored', 0)} field crops")
    for bucket in ("redacted", "no_ground_truth"):
        count = counts.get(bucket, 0)
        lines.append(f"- **{bucket}**: {count} field crops -- {_BUCKET_REASONS[bucket]}")
    lines.append("")
    return "\n".join(lines)


def _render_no_ground_truth_section(records: list[ScoredCrop]) -> str:
    entries = no_ground_truth_records(records)
    lines = [
        "### No usable ground truth -- not scored, OCR output shown for inspection",
        "",
        "These rows are excluded from every accuracy number above. Reported here so the raw"
        " model output on genuinely illegible source material stays visible rather than"
        " hidden. This is a measurement, not a pass/fail check -- a bad reading here is"
        " expected, not a bug.",
        "",
    ]
    if not entries:
        lines.append("(none)")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Sheet | Row | Field | OCR text (verbatim) | OCR confidence |")
    lines.append("|---|---|---|---|---|")
    for entry in entries:
        ocr_text = entry.ocr_text if entry.ocr_text else "(nothing recognized)"
        confidence = f"{entry.confidence:.3f}" if entry.confidence is not None else "--"
        lines.append(
            f"| {entry.sheet_id} | {entry.row} | {entry.field_name} | {ocr_text}"
            f" | {confidence} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_run_metadata(metadata: RunMetadata) -> str:
    return "\n".join(
        [
            "### Run environment",
            "",
            f"- Model: PP-OCRv6 ({metadata.model_tier} tier)",
            f"- paddleocr: {metadata.paddleocr_version}",
            f"- paddlepaddle: {metadata.paddlepaddle_version}",
            f"- Device: {metadata.device}",
            f"- Total wall-clock time: {metadata.total_wall_clock_seconds:.1f}s",
            "",
        ]
    )


def render_markdown_report(records: list[ScoredCrop], metadata: RunMetadata) -> str:
    """Render the full baseline report: rules, per-field table, exclusions, run info."""
    sections = [
        "# PP-OCRv6 baseline: real golden-fixture accuracy",
        "",
        "This is a measurement, not a pass/fail gate. Numbers are reported as produced,"
        " with no filtering or tuning to improve them -- see Task C1 in"
        " IMPLEMENTATION_PLAN.md.",
        "",
        _CANONICALIZATION_RULES_TEXT,
        _render_field_table("All sheets combined", records),
        _render_bucket_counts(records),
        _render_no_ground_truth_section(records),
        _render_run_metadata(metadata),
    ]

    sheet_ids = sorted({record.sheet_id for record in records})
    sections.append("## Per-sheet breakdown")
    sections.append("")
    for sheet_id in sheet_ids:
        sheet_records = [r for r in records if r.sheet_id == sheet_id]
        sections.append(_render_field_table(sheet_id, sheet_records))

    return "\n".join(sections)


def render_json_records(records: list[ScoredCrop]) -> str:
    """One JSON record per tagged field crop, safe to commit (no guest names)."""
    return json.dumps([record.as_json_dict() for record in records], indent=2, sort_keys=True)
