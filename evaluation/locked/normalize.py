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
# zone fatalities" (locked wztc-089). A leading quantifier counts the same way: "all projects" answered
# "all Federal-aid projects" (held-out utilities-h066, DAR-737).
_COUNT_MODIFIERS = 2
_QUANTIFIERS = frozenset({"all", "each", "every", "any", "both"})
# Endings that only change a word's number or tense: "prohibited" answered "prohibits" (held-out
# utilities-h087, DAR-737). Tried in this order; a stem keeps at least 3 letters, so "uses", "used" and
# "use" are all "use". "-ing" is not stripped: "engineering" is not "engineer".
_ENDINGS = ("es", "ed", "s", "d", "e")


def _stem(word: str) -> str:
    """The word without one plural or past-tense ending; numbers and short words unchanged."""
    if len(word) < 4 or not word.isalpha():
        return word
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[:-len(ending)]
    return word


def _words(text: str) -> List[str]:
    return [_stem(w) for w in _WORD.findall(text) if w not in _FILLER]


def _words_in_order(wanted: str, answer: str) -> bool:
    """Whether a phrase value's words appear in the answer in order, with only the gaps a wording allows.

    Scorer-only, for phrase values (never a single number). Words are compared without their plural or
    past-tense ending (_stem). Besides filler words, three gaps are allowed: a word of the value repeated
    ("Class 2 or 3" answered "Class 2 or Class 3", locked wztc-083); up to _COUNT_MODIFIERS words between a
    value's leading number or quantifier and its noun (not inside a ratio: "16:1 anchored" is not "16:1 when
    anchored"); and once, a second verb or noun joined by "and"/"or" ("Revise the TMP" answered "revise and
    implement the TMP", held-out wztc-h097, DAR-737). Any other word in between breaks the match, so
    "Division Utility" is not found in "Division Project/Utility personnel" (locked utilities-041, a wrong
    answer).
    """
    want, have = _words(wanted), _words(answer)
    if len(want) < 2 or not any(w[0].isalpha() for w in want):
        return False
    leads_count = want[0][0].isdigit() or want[0] in _QUANTIFIERS
    for start, word in enumerate(have):
        if word != want[0]:
            continue
        j, i, gap, joined = 1, start + 1, 0, False
        while j < len(want) and i < len(have):
            if have[i] == want[j]:
                j, gap = j + 1, 0
            elif have[i] in want[:j]:
                pass
            elif j == 1 and leads_count and want[1][0].isalpha() and gap < _COUNT_MODIFIERS:
                gap += 1
            elif (not joined and have[i] in ("and", "or") and i + 2 < len(have) and have[i + 1][0].isalpha()
                  and have[i + 2] == want[j]):
                joined, i = True, i + 1
            else:
                break
            i += 1
        if j == len(want):
            return True
    return False


def _words_reordered(wanted: str, answer: str) -> bool:
    """Whether the answer has exactly a phrase value's words, side by side in another order.

    Scorer-only. English puts a modifier before or after its noun: "crossings at grade" is "at-grade
    crossings" (held-out tmsd-h089), "long project duration" is "the project has a long duration"
    (wztc-h079), "listen and look" is "look and listen" (tmsd-h085; DAR-737). The words must be the same
    ones (filler aside, endings stemmed) with nothing else between them, so a reordering cannot pull in
    a word from elsewhere in the sentence. Values with a number are never reordered: "Class 2 or 3" is
    not "Class 3 or 2" for a scorer that can't tell which order matters.
    """
    want, have = _words(wanted), _words(answer)
    if len(want) < 2 or not all(w.isalpha() for w in want):
        return False
    target = sorted(want)
    return any(sorted(have[i:i + len(want)]) == target for i in range(len(have) - len(want) + 1))


# Two to six capitals, the way the manuals abbreviate a document or body: TMP, MOU, UAM, MUTCD.
_ACRONYM = re.compile(r"\b[A-Z]{2,6}\b")
# Small words an acronym skips: "MOU" is "memoranda of understanding".
_ACRONYM_SKIPS = frozenset({"of", "and", "for", "the", "on", "in", "to", "&"})
_LETTER_WORD = re.compile(r"[A-Za-z]+|&")


def _contract(text: str, acronyms: Sequence[str]) -> str:
    """The text with each spelled-out form of an acronym replaced by the acronym.

    Scorer-only. "Implement the TMP" is answered "Implement the transportation management plan (TMP)"
    (held-out wztc-h097, DAR-737): a run of words whose initials spell an acronym found on either side
    becomes that acronym, on both sides, before the phrase match.
    """
    if not acronyms:
        return text
    words = list(_LETTER_WORD.finditer(text))
    spans = []
    for acronym in acronyms:
        letters = acronym.lower()
        for start in range(len(words)):
            k, n = start, 0
            while k < len(words) and n < len(letters):
                raw = words[k].group(0)
                word = raw.lower()
                # A small word stands for its letter when it has it ("DOT" is "Department of Transportation").
                if word in _ACRONYM_SKIPS and n > 0 and word[0] != letters[n]:
                    k += 1
                    continue
                # An acronym is not the spelled-out form of another one.
                if word[0] != letters[n] or (len(raw) > 1 and raw.isupper()):
                    break
                n, k = n + 1, k + 1
            if n == len(letters) and k - start > 1:
                spans.append((words[start].start(), words[k - 1].end(), acronym))
    out, last = [], 0
    for begin, end, acronym in sorted(spans):
        if begin < last:
            continue
        out += [text[last:begin], acronym]
        last = end
    return "".join(out) + text[last:]


# A number joined to a later number that carries a unit: "between 75 and 90 degrees" states 75 degrees
# (held-out tmsd-h016), "stop 15 to 50 feet" states 15 feet (tmsd-h085; DAR-737). Normalized text.
_RANGE_START = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?=(?:\s*-\s*|\s*,\s*(?:and\s+|or\s+)?|\s+(?:to|and|or|through)\s+)"
                          r"\d+(?:\.\d+)?\s(ft|in" + _PREPOSITION + r"|mph|%|deg)(?![a-z%]))")


def _one_word(wanted: str, answer: str) -> bool:
    """A one-word phrase value found as a word of the answer once both lose their endings ("prohibited"
    answered "prohibits"). Scorer-only."""
    want = _words(wanted)
    return len(want) == 1 and want[0].isalpha() and want[0] in _words(answer)


def _range_units(text: str) -> str:
    """Normalized text where each number at the start of a range or list carries the unit of its end."""
    previous = None
    while previous != text:
        previous, text = text, _RANGE_START.sub(lambda m: f"{m.group(1)} {m.group(2)}", text)
    return text


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
    acronyms = sorted(set(_ACRONYM.findall(answer_text or "")).union(*(_ACRONYM.findall(str(c)) for c in candidates)))
    answer = normalize(answer_text)
    # Scorer-only forms of the answer: ranges with the unit on each end, and spelled-out acronyms contracted.
    ranged = _range_units(answer)
    phrased = normalize(_contract(answer_text or "", acronyms))
    numbers = numbers_with_units(ranged)
    for candidate in candidates:
        wanted = normalize(str(candidate))
        single = _single_number(wanted)
        if single is None:
            short = normalize(_contract(str(candidate), acronyms))
            if wanted and (wanted in answer or _phrase_form(wanted) in _phrase_form(answer)
                           or wanted in ranged
                           or _words_in_order(wanted, answer)
                           or _words_in_order(_phrase_form(wanted), _phrase_form(answer))
                           or _words_in_order(short, phrased) or _words_reordered(short, phrased)
                           or _one_word(short, phrased)):
                return True
            continue
        value, unit = single
        for found, found_unit, _ in numbers:
            if abs(found - value) <= TOLERANCE and (unit is None or found_unit == unit):
                return True
    return False
