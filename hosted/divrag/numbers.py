"""Number and unit normalization, shared with the DAR-652 locked-set scorer.

A copy of evaluation/locked/normalize.py (hosted/ may not import from
evaluation/, and Vercel deploys hosted/ alone): keep the two identical, so an
answer the scorer accepts is one the number check (verify.py) accepts too. The
rules, applied in this order to lowercased text:

    thousands commas       1,640 -> 1640
    fractions              1/2 -> 0.5, 1-1/2 and 1 1/2 -> 1.5, ½ -> 0.5
    trailing zeros         12.0 -> 12, 12.50 -> 12.5
    feet                   12', 12-foot, 12 feet, 12 ft. -> 12 ft
    inches                 12", 12 inch, 12 inches, 12 in. -> 12 in
    speed                  12 mph, 12 mi/h, 12 miles per hour -> 12 mph
    percent                12%, 12 percent -> 12 %
    degrees                12°, 12 deg, 12 degrees -> 12 deg

A unit is only rewritten when a number comes right before it, so "the width in
feet" keeps its words. Numbers are compared as floats within 1e-9 once the
units agree; anything that is not a single number is matched as a phrase,
case-insensitively, with whitespace collapsed.
"""

import re
from typing import List, Optional, Sequence, Tuple

TOLERANCE = 1e-9
UNITS = ("ft", "in", "mph", "%", "deg")

_UNICODE = {
    "′": "'", "″": '"', "“": '"', "”": '"', "‘": "'", "’": "'",
    "–": "-", "—": "-", "−": "-", " ": " ",
    "½": " 1/2", "¼": " 1/4", "¾": " 3/4", "⅓": " 1/3", "⅔": " 2/3", "⅛": " 1/8",
}
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
# "1-1/2", "1 1/2" or "1/2": a whole part joined by a hyphen or a space, then numerator/denominator.
_FRACTION = re.compile(r"(?<![\w./])(?:(\d+)[-\s])?(\d+)/(\d+)(?![\w/])")
_TRAILING_ZEROS = re.compile(r"(?<![\w.])(\d+)\.(\d*?)0*(?![\d])")
# Each unit: the number, optional space or hyphen, the unit's spellings, no letter right after
# (so "12 into" is not "12 in", and "12 ft." loses its dot).
_NUMBER = r"(?<![\w.])(\d+(?:\.\d+)?)"
_FEET = re.compile(_NUMBER + r"\s*(?:'|-?\s*(?:feet|foot|ft)\.?)(?![a-z])")
# A bare "in" followed by an article or determiner is the preposition ("reduce to 11 in the work zone"),
# not inches; "12 in. wide", "12 in wide" and "12 in" at the end stay inches.
_PREPOSITION = r"(?!\s+(?:the|a|an|each|every|this|that|these|those|which|order|addition|all|both|any|most|some)\b)"
_INCHES = re.compile(_NUMBER + r"\s*(?:\"|-?\s*(?:inches|inch|in\.|in" + _PREPOSITION + r"))(?![a-z])")
_MPH = re.compile(_NUMBER + r"\s*-?\s*(?:mph|mi/h|miles?\s+per\s+hour)\.?(?![a-z])")
_PERCENT = re.compile(_NUMBER + r"\s*(?:%|percent|per\s+cent)(?![a-z])")
_DEGREES = re.compile(_NUMBER + r"\s*(?:°|-?\s*deg(?:rees?|\.)?)(?![a-z])")
_UNIT_PATTERNS = ((_FEET, "ft"), (_INCHES, "in"), (_MPH, "mph"), (_PERCENT, "%"), (_DEGREES, "deg"))
# A number in normalized text, with the unit that follows it when there is one.
_NUMBER_WITH_UNIT = re.compile(_NUMBER + r"(?:\s(ft|in" + _PREPOSITION + r"|mph|%|deg)(?![a-z%]))?")


def _fraction(match: "re.Match[str]") -> str:
    whole, numerator, denominator = match.group(1), int(match.group(2)), int(match.group(3))
    if denominator == 0:
        return match.group(0)
    value = (int(whole) if whole else 0) + numerator / denominator
    return _number_text(value)


def _number_text(value: float) -> str:
    """A float as the shortest plain decimal: 1.5, 0.5, 27.42, 12 (never 12.0 or 1e-05)."""
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text or "0"


def _trailing_zeros(match: "re.Match[str]") -> str:
    whole, decimals = match.group(1), match.group(2)
    return f"{whole}.{decimals}" if decimals else whole


def normalize(text: str) -> str:
    """The text with numbers and units in their one spelling, lowercased, whitespace collapsed."""
    out = (text or "").lower()
    for char, replacement in _UNICODE.items():
        out = out.replace(char, replacement)
    out = _THOUSANDS.sub("", out)
    out = _FRACTION.sub(_fraction, out)
    out = _TRAILING_ZEROS.sub(_trailing_zeros, out)
    for pattern, unit in _UNIT_PATTERNS:
        out = pattern.sub(lambda m, u=unit: f"{m.group(1)} {u}", out)
    return " ".join(out.split())


def numbers_with_units(text: str) -> List[Tuple[float, Optional[str], str]]:
    """Every number in the text after normalization: (value, unit or None, the span as normalized)."""
    found = []
    for match in _NUMBER_WITH_UNIT.finditer(normalize(text)):
        found.append((float(match.group(1)), match.group(2), match.group(0)))
    return found


def _single_number(text: str) -> Optional[Tuple[float, Optional[str]]]:
    """(value, unit) when the normalized text is exactly one number with at most a unit after it."""
    match = _NUMBER_WITH_UNIT.fullmatch(text)
    return (float(match.group(1)), match.group(2)) if match else None


def value_matches(expected_value: Optional[str], accept: Optional[Sequence[str]], answer_text: str) -> bool:
    """Whether the answer states the expected value or any accepted alternative.

    A candidate that is one number (with or without a unit) matches a number
    in the answer within TOLERANCE; with a unit, the answer's number must carry
    the same unit. Any other candidate (a phrase, a ratio like "16:1", two
    numbers) must appear in the normalized answer as a substring.
    """
    candidates = [c for c in [expected_value, *(accept or [])] if c is not None and str(c).strip()]
    if not candidates:
        return False
    answer = normalize(answer_text)
    numbers = numbers_with_units(answer)
    for candidate in candidates:
        wanted = normalize(str(candidate))
        single = _single_number(wanted)
        if single is None:
            if wanted and wanted in answer:
                return True
            continue
        value, unit = single
        for found, found_unit, _ in numbers:
            if abs(found - value) <= TOLERANCE and (unit is None or found_unit == unit):
                return True
    return False
