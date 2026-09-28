"""Canonical field values shared by validation and fixture scoring.

Keep OCR source text separate; these functions only normalize validation input.
"""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Final

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
