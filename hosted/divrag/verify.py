"""The number check: every number an answer states must be in the passages it cites.

The free models misread tables: asked for the maximum deflection at a 14 ft
offset and 40 mph (TMP manual p.37), one gave a neighbouring row's value with a
correct citation, so the citation alone looked right. Checking each number of
the answer against the cited passages' text (numbers.py normalizes "12-foot"
and "12 ft", "1-1/2" and "1.5" to one spelling first) catches a number the
passages don't contain, whatever produced it: a wrong cell, a conversion, a
calculation, or a number from outside the documents.

It is a string check, not a reading of the table: it can't tell that 27.42 came
from the wrong row when 27.42 is also somewhere else in the passage. What it
flags is a number that is in none of them.
"""

import re
from typing import Iterable, List, Optional, Sequence, Tuple

from .numbers import TOLERANCE, numbers_with_units

# Citation markers ("[1]", "[1, 2]", "【2】") are not numbers the answer states.
_CITATION = re.compile(r"[\[【［]\s*\d+(?:\s*[,;\-–]\s*\d+)*\s*[\]】］]")
# Neither is a numbered-list marker at the start of a line ("1. Close the lane"),
# an ordinal ("the 2nd lane") or a clock time ("8:00 a.m."): none is a value read
# from a table, and the passage may spell them differently ("second", "8 a.m.").
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
_ORDINAL_OR_TIME = re.compile(r"(?<![\w.])\d+(?:st|nd|rd|th)\b|(?<![\w.])\d{1,2}:\d{2}\b", re.IGNORECASE)
# Quoted labels: rule 5 and NUMBERS_RULE ask the model to quote the row and column
# it used ('the row "14" and the column "40 mph"'), and numbers.py reads a number
# before a double quote as inches (12" pipe). The quotes are dropped from the
# answer, so a quoted 14 is a bare 14; a bare number is only more lenient.
_QUOTED = re.compile(r"[\"“”]([^\"“”\n]{1,80})[\"“”]")


def _stated(answer: str) -> str:
    text = _LIST_MARKER.sub("", _CITATION.sub(" ", answer))
    return _ORDINAL_OR_TIME.sub(" ", _QUOTED.sub(r" \1 ", text))


def _found(value: float, unit: Optional[str], known: Iterable[Tuple[float, Optional[str], str]]) -> bool:
    """The value is among the known numbers, with the same unit when both carry one.

    A table cell rarely repeats the unit, which is in the column header
    ("Max deflection (ft)" over "27.42"), so a passage's bare 27.42 verifies the
    answer's "27.42 ft". A number with a different unit (27.42 in) does not.
    """
    return any(abs(value - v) <= TOLERANCE and (unit is None or u is None or unit == u) for v, u, _ in known)


def unverified_numbers(answer: str, references: Sequence[str], question: str = "",
                       labels: Sequence[str] = ()) -> List[str]:
    """The numbers in `answer` found in none of `references`, normalized ("27.5 ft"), in order, once each.

    Numbers from the question count as found: an answer that restates "an
    offset of 14 ft at 40 mph" is repeating the visitor, not the documents.
    Numbers in `labels` (the passages' locators: "PDF page 12, section 3.6")
    verify only a bare number, so "see page 12" passes while "12 ft" on page 12
    is still checked against the passage text.
    """
    known = numbers_with_units("\n".join([question, *references]))
    label_numbers = [(value, None, raw) for value, _, raw in numbers_with_units("\n".join(labels))]
    missing: List[str] = []
    for value, unit, raw in numbers_with_units(_stated(answer)):
        if _found(value, unit, known) or (unit is None and _found(value, None, label_numbers)):
            continue
        if raw not in missing:
            missing.append(raw)
    return missing
