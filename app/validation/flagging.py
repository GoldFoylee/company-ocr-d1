"""Combine OCR confidence and business-rule validation into review flags."""

from dataclasses import dataclass
from typing import Final

from app.validation.engine import ValidationResult

DEFAULT_REVIEW_CONFIDENCE_THRESHOLD: Final = 0.85


@dataclass(frozen=True, slots=True)
class FlaggingDecision:
    """Values ready to store as an extraction's review flag and reason."""

    rule_flag: bool
    rule_flag_reason: str | None


def decide_field_flag(
    ocr_text: str,
    ocr_confidence: float,
    validation_result: ValidationResult,
    *,
    confidence_threshold: float = DEFAULT_REVIEW_CONFIDENCE_THRESHOLD,
) -> FlaggingDecision:
    """Return the review decision from independent confidence and rule signals.

    A failed validation always flags the field. Low OCR confidence is a separate
    trigger and is also retained in the reason when both signals require review.
    """
    _validate_normalized_score(ocr_confidence, name="ocr_confidence")
    _validate_normalized_score(confidence_threshold, name="confidence_threshold")

    reasons: list[str] = []
    if not validation_result.passed:
        reasons.append(
            f"Validation failed ({validation_result.rule}): {validation_result.reason}"
        )

    if ocr_confidence < confidence_threshold:
        reasons.append(
            f"Low OCR confidence for {ocr_text!r}: {ocr_confidence} is below "
            f"the {confidence_threshold} review threshold"
        )

    if not reasons:
        return FlaggingDecision(rule_flag=False, rule_flag_reason=None)

    return FlaggingDecision(rule_flag=True, rule_flag_reason="; ".join(reasons))


def _validate_normalized_score(score: float, *, name: str) -> None:
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")
