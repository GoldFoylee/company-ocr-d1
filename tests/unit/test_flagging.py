"""Tests for combining OCR confidence and validation into review flags."""

import pytest

from app.validation import (
    DEFAULT_REVIEW_CONFIDENCE_THRESHOLD,
    FlaggingDecision,
    ValidationResult,
    decide_field_flag,
)


def make_validation_result(*, passed: bool) -> ValidationResult:
    return ValidationResult(
        rule="kilometre_total",
        passed=passed,
        reason=(
            "1150 - 1000 = 150"
            if passed
            else "kilometre mismatch: computed 150, reported 140"
        ),
    )


@pytest.mark.parametrize(
    ("ocr_confidence", "validation_passed", "expected_flag", "reason_fragments"),
    [
        (0.95, True, False, ()),
        (0.70, True, True, ("Low OCR confidence", "0.7", "0.85")),
        (
            0.95,
            False,
            True,
            ("Validation failed", "kilometre_total", "kilometre mismatch"),
        ),
        (
            0.70,
            False,
            True,
            ("Validation failed", "kilometre mismatch", "Low OCR confidence"),
        ),
    ],
    ids=(
        "high-confidence-validation-pass",
        "low-confidence-validation-pass",
        "high-confidence-validation-fail",
        "low-confidence-validation-fail",
    ),
)
def test_flagging_decision_matrix(
    ocr_confidence: float,
    validation_passed: bool,
    expected_flag: bool,
    reason_fragments: tuple[str, ...],
) -> None:
    decision = decide_field_flag(
        "1150",
        ocr_confidence,
        make_validation_result(passed=validation_passed),
    )

    assert decision.rule_flag is expected_flag
    if not expected_flag:
        assert decision.rule_flag_reason is None
        return

    assert decision.rule_flag_reason is not None
    for fragment in reason_fragments:
        assert fragment in decision.rule_flag_reason


def test_default_threshold_is_named_and_matches_environment_example() -> None:
    assert DEFAULT_REVIEW_CONFIDENCE_THRESHOLD == 0.85


def test_threshold_is_configurable_and_inclusive() -> None:
    validation_result = make_validation_result(passed=True)

    at_threshold = decide_field_flag(
        "1150", 0.60, validation_result, confidence_threshold=0.60
    )
    below_threshold = decide_field_flag(
        "1150", 0.59, validation_result, confidence_threshold=0.60
    )

    assert at_threshold == FlaggingDecision(rule_flag=False, rule_flag_reason=None)
    assert below_threshold.rule_flag is True
    assert below_threshold.rule_flag_reason is not None
    assert "0.6 review threshold" in below_threshold.rule_flag_reason


@pytest.mark.parametrize(
    ("ocr_confidence", "confidence_threshold", "expected_name"),
    [
        (-0.01, DEFAULT_REVIEW_CONFIDENCE_THRESHOLD, "ocr_confidence"),
        (1.01, DEFAULT_REVIEW_CONFIDENCE_THRESHOLD, "ocr_confidence"),
        (0.90, -0.01, "confidence_threshold"),
        (0.90, 1.01, "confidence_threshold"),
    ],
)
def test_scores_must_be_normalized(
    ocr_confidence: float, confidence_threshold: float, expected_name: str
) -> None:
    with pytest.raises(ValueError, match=expected_name):
        decide_field_flag(
            "1150",
            ocr_confidence,
            make_validation_result(passed=True),
            confidence_threshold=confidence_threshold,
        )
