"""Tests for matching noisy OCR name guesses to canonical roster names."""

import pytest

from app.matching import NameMatch, find_best_name_match


@pytest.mark.parametrize(
    ("ocr_name", "expected_name"),
    [
        ("Micheal Thompson", "Michael Thompson"),
        ("Priya Niar", "Priya Nair"),
        ("Jon Smyth", "John Smith"),
    ],
)
def test_known_typos_match_the_correct_roster_name(ocr_name: str, expected_name: str) -> None:
    roster = ["Michael Thompson", "Priya Nair", "John Smith", "Aisha Khan"]

    result = find_best_name_match(ocr_name, roster, threshold=75.0)

    assert result is not None
    assert result.canonical_name == expected_name
    assert result.score >= 75.0


def test_unrelated_name_does_not_match_above_threshold() -> None:
    roster = ["Michael Thompson", "Priya Nair", "John Smith"]

    result = find_best_name_match("Zelda Quimby", roster, threshold=80.0)

    assert result is None


def test_threshold_controls_borderline_match() -> None:
    roster = ["Joanna Lee"]

    permissive_result = find_best_name_match("Joan Lee", roster, threshold=80.0)
    strict_result = find_best_name_match("Joan Lee", roster, threshold=95.0)

    assert permissive_result is not None
    assert strict_result is None


def test_matching_normalizes_case_punctuation_and_spacing() -> None:
    result = find_best_name_match(
        "  MARIA   JOSE  O'NEIL ",
        ["Maria-Jose O'Neil", "Mario Jones"],
        threshold=100.0,
    )

    assert result == NameMatch(canonical_name="Maria-Jose O'Neil", score=100.0)


def test_checkpoint_garbled_name_gets_a_sensible_correction() -> None:
    roster = ["Katherine Johnson", "Catherine Jones", "Kevin Johnston"]

    result = find_best_name_match("Katherne Jhnson", roster, threshold=80.0)

    assert result is not None
    assert result.canonical_name == "Katherine Johnson"
    assert result.score >= 80.0


def test_empty_or_blank_input_returns_no_match() -> None:
    assert find_best_name_match("", ["John Smith"]) is None
    assert find_best_name_match("   ", ["John Smith"]) is None
    assert find_best_name_match("John Smith", []) is None
    assert find_best_name_match("John Smith", ["", "   "]) is None


@pytest.mark.parametrize("threshold", [-0.1, 100.1])
def test_threshold_must_be_a_percentage(threshold: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        find_best_name_match("John Smith", ["John Smith"], threshold=threshold)
