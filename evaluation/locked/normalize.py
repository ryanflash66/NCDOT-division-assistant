"""Number and unit normalization for scoring answers against the gold value.

Pure Python, no dependencies: the hosted number guardrail copies these exact
rules, so an answer the scorer accepts is one the guardrail would too. The
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
    # The MUTCD sign tables print sizes as "64 × 64 × 48"; answers copy the ×, gold values use x.
    "×": "x",
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


_NUMBER_HYPHEN_WORD = re.compile(r"(\d)\s*-\s*(?=[a-z])")
_PLURAL_AFTER_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)? [a-z]+?)s\b")


def _phrase_form(text: str) -> str:
    """Normalized text with "12-month" as "12 month" and "12 months" as "12 month", for phrase values only.

    Scorer-only (the hosted guardrail compares numbers, not phrases): the UAM's
    bond release (locked utilities-021) is "1 year", accepted as "12 months",
    and an answer saying "the 12-month warranty period" was scored wrong.
    """
    return _PLURAL_AFTER_NUMBER.sub(r"\1", _NUMBER_HYPHEN_WORD.sub(r"\1 ", text))


_WORD = re.compile(r"\d+(?:\.\d+)?|[a-z]+|%")
# Articles and auxiliaries carry no part of a value: the Encroachment guide's SR0000 rule (locked
# utilities-053) is gold "not yet been assigned a number", answered "has not yet assigned a number".
_FILLER = frozenset({"a", "an", "the", "be", "been", "is", "are", "was", "were", "has", "have", "had"})
# Words that may sit between a number and the noun it counts: "27 fatalities" answered as "27 work
# zone fatalities" (locked wztc-089).
_COUNT_MODIFIERS = 2


def _words(text: str) -> List[str]:
    return [w for w in _WORD.findall(text) if w not in _FILLER]


def _words_in_order(wanted: str, answer: str) -> bool:
    """Whether a phrase value's words appear in the answer in order, with only the gaps a wording allows.

    Scorer-only, for phrase values (never a single number). Besides filler words, two gaps are allowed:
    a word of the value repeated ("Class 2 or 3" answered "Class 2 or Class 3", locked wztc-083), and up
    to _COUNT_MODIFIERS words between a value's leading number and its noun (not inside a ratio: "16:1
    anchored" is not "16:1 when anchored"). Any other word in between breaks the match, so "Division
    Utility" is not found in "Division Project/Utility personnel" (locked utilities-041, a wrong answer).
    """
    want, have = _words(wanted), _words(answer)
    if len(want) < 2 or not any(w[0].isalpha() for w in want):
        return False
    for start, word in enumerate(have):
        if word != want[0]:
            continue
        j, i, gap = 1, start + 1, 0
        while j < len(want) and i < len(have):
            if have[i] == want[j]:
                j, gap = j + 1, 0
            elif have[i] in want[:j]:
                pass
            elif j == 1 and want[0][0].isdigit() and want[1][0].isalpha() and gap < _COUNT_MODIFIERS:
                gap += 1
            else:
                break
            i += 1
        if j == len(want):
            return True
    return False


def value_matches(expected_value: Optional[str], accept: Optional[Sequence[str]], answer_text: str) -> bool:
    """Whether the answer states the expected value or any accepted alternative.

    A candidate that is one number (with or without a unit) matches a number
    in the answer within TOLERANCE; with a unit, the answer's number must carry
    the same unit. Any other candidate (a phrase, a ratio like "16:1", two
    numbers) must appear in the normalized answer as a substring, or as its
    words in order with only filler words, a repeated word or a count's
    modifiers between them (_words_in_order).
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
            if wanted and (wanted in answer or _phrase_form(wanted) in _phrase_form(answer)
                           or _words_in_order(wanted, answer)
                           or _words_in_order(_phrase_form(wanted), _phrase_form(answer))):
                return True
            continue
        value, unit = single
        for found, found_unit, _ in numbers:
            if abs(found - value) <= TOLERANCE and (unit is None or found_unit == unit):
                return True
    return False
