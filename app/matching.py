"""Fuzzy matching for noisy OCR names and canonical roster entries."""

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz


@dataclass(frozen=True, slots=True)
class NameMatch:
    """A canonical roster name and its 0-to-100 similarity score."""

    canonical_name: str
    score: float


def find_best_name_match(
    ocr_name: str,
    roster_names: Iterable[str],
    *,
    threshold: float = 80.0,
) -> NameMatch | None:
    """Return the closest roster name when its score meets ``threshold``.

    Matching ignores capitalization, punctuation, and repeated whitespace. The
    original roster spelling is returned so downstream code receives the
    canonical value rather than the normalized comparison text.
    """
    if not 0.0 <= threshold <= 100.0:
        raise ValueError("threshold must be between 0 and 100")

    normalized_query = _normalize_name(ocr_name)
    if not normalized_query:
        return None

    best_name: str | None = None
    best_score = -1.0

    for canonical_name in roster_names:
        normalized_candidate = _normalize_name(canonical_name)
        if not normalized_candidate:
            continue

        score = float(fuzz.ratio(normalized_query, normalized_candidate))
        if score > best_score:
            best_name = canonical_name
            best_score = score

    if best_name is None or best_score < threshold:
        return None

    return NameMatch(canonical_name=best_name, score=best_score)


def _normalize_name(name: str) -> str:
    """Create comparison text without changing the canonical roster value."""
    normalized = unicodedata.normalize("NFKC", name).casefold()
    words = "".join(character if character.isalnum() else " " for character in normalized)
    return " ".join(words.split())
