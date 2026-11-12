"""A second model's opinion on the numbers of an answer (DAR-663).

The number check (verify.py, DAR-659) flags a number the cited passages don't
contain. It cannot flag a number read from the wrong cell of the right table:
on the locked split 8 of 232 answers were confident and wrong, and in all 8 the
wrong number was printed on the cited page (the model read the wrong row or
column; with 8 passages, a first answer on the tuning split read the wrong row
of Detail 3-2A, docs/redo-decision-log.md D15). A second model reading the same
passages for the same question seldom misreads the same cell, so when the two
answers state different numbers, the first answer's numbers that the second
contradicts are returned to be flagged as unverified.

What is compared is the numbers that answer the question. Left out are:

- citation markers, list markers, ordinals and clock times (verify's rules);
- page references ("p.13 (PDF page 37)", rule 8 of the prompt asks for them);
- identifiers ("Table 6-1", "Detail 3-2A", "Section 3.6"): one model naming
  the table and the other not is no disagreement about its value;
- numbers the question (or an earlier question) gave, as the number check
  leaves them out: "at 40 mph" repeats the visitor.

A number of the first answer is contradicted when the second answer doesn't
state it and states a number of its own that the first doesn't, of the same
kind (the same unit, or a bare number). An answer that states fewer numbers
(the second leaves out a context number, or the first adds the metric
conversion) is an omission, not a contradiction, and flagging it would only add
false alarms; so is a "12 ft" against the other answer's "6 in". Numbers are
compared with numbers.py's normalization (12-foot and 12 ft are one number, a
bare 27.42 matches 27.42 ft), and inches and feet are compared as lengths
(18 in is 1.5 ft).

The second model is the next free model of the configured chain after the one
that answered, never the one that answered (it would repeat its own misread),
never one that refused this question, and never a paid one: when OpenAI
answered (FallbackClient), the second opinion comes from the first free model,
so the check never spends OpenAI money twice.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .config import FREE_SUFFIX
from .llm import LLMError
from .numbers import TOLERANCE, numbers_with_units
from .verify import _stated

log = logging.getLogger(__name__)

Number = Tuple[float, Optional[str], str]

# "PDF page 37", "p.13", "pp. 12-13", "pages 36 to 38": where a value is, not the value.
_PAGE_REF = re.compile(
    r"\b(?:pdf\s+)?(?:pages?|pp?\.)\s*\d+[a-z]?(?:\s*(?:[-–]|to|and)\s*\d+[a-z]?)?", re.IGNORECASE)
_ID_NUMBER = r"\s*(?:no\.\s*)?[A-Za-z]?\d+(?:[.\-–]\d+)*[A-Za-z]?\b"
# "Table 6-1", "Detail 3-2A", "Section 3.6", "Std. No. 1101.02": the name of a table or rule, not a value read from it.
_IDENTIFIER = re.compile(
    r"\b(?:(?i:table|figure|fig\.|detail|section|sect\.|chapter|appendix|standard|std\.|drawing|exhibit|article|"
    r"sheet|plate|vol\.)"
    # Everyday words name an identifier only capitalized and singular ("Type 3", "Case 2", "Row 14"):
    # "in both cases 500 ft" or "for all types 36 in" state the value.
    r"|Note|Item|Step|Type|Class|Case|Option|Row|Column|Part|Level|Group|Form)" + _ID_NUMBER)
# Lengths in one unit, so "18 in" and "1.5 ft" are the same reading of a cell.
_TO_FEET = {"in": 1 / 12}


def _canonical(number: Number) -> Tuple[float, Optional[str]]:
    value, unit, _ = number
    if unit in _TO_FEET:
        return value * _TO_FEET[unit], "ft"
    return value, unit


def _kind_matches(a: Number, b: Number) -> bool:
    """The same unit after converting lengths, or a bare number on either side (a cell rarely repeats its unit)."""
    ua, ub = _canonical(a)[1], _canonical(b)[1]
    return ua is None or ub is None or ua == ub


def _same(a: Number, b: Number) -> bool:
    return _kind_matches(a, b) and abs(_canonical(a)[0] - _canonical(b)[0]) <= TOLERANCE * max(1.0, abs(a[0]))


def answer_numbers(text: str, asked: str = "") -> List[Number]:
    """The numbers in an answer that answer the question, once each, in order (see the module notes)."""
    given = numbers_with_units(asked)
    cleaned = _IDENTIFIER.sub(" ", _PAGE_REF.sub(" ", _stated(text)))
    found: List[Number] = []
    for number in numbers_with_units(cleaned):
        if any(_same(number, g) for g in given) or any(number[2] == f[2] for f in found):
            continue
        found.append(number)
    return found


def disagreeing(first: Sequence[Number], second: Sequence[Number]) -> Tuple[List[str], List[str]]:
    """(the first answer's numbers the second contradicts, the second's numbers that contradict them).

    ([], []) when they agree, or when one answer only leaves numbers out.
    """
    first_only = [a for a in first if not any(_same(a, b) for b in second)]
    second_only = [b for b in second if not any(_same(b, a) for a in first)]
    flagged = [a for a in first_only if any(_kind_matches(a, b) for b in second_only)]
    instead = [b for b in second_only if any(_kind_matches(b, a) for a in flagged)]
    return list(dict.fromkeys(a[2] for a in flagged)), list(dict.fromkeys(b[2] for b in instead))


def second_opinion_models(llm: Any, used: str, avoid: Sequence[str] = ()) -> List[str]:
    """The free models to ask for a second opinion after `used` answered, in the order to try; [] when there is none.

    The models after `used` in the configured chain come first, then the ones
    before it, so the last model's answer is checked by the first. `avoid` are
    models that refused this question (before a retry): asked the same
    messages, they would refuse again and give no opinion. When the chain
    doesn't know `used`, which model answered is unknown, and the check is
    skipped rather than risk asking that model to check itself.
    """
    chain = list(getattr(llm, "models", None) or [])
    names = [m.removesuffix(FREE_SUFFIX) for m in chain]
    known = used if used in chain else None
    if known is None and used.removesuffix(FREE_SUFFIX) in names:
        known = chain[names.index(used.removesuffix(FREE_SUFFIX))]
    if known is None:
        log.warning("number agreement skipped: %s is not in the model list", used)
        return []
    at = chain.index(known)
    ordered = chain[at + 1:] + chain[:at]
    return [m for m in dict.fromkeys(ordered) if m.endswith(FREE_SUFFIX) and m not in avoid]


@dataclass
class SecondOpinion:
    """What the second model's answer said about the first answer's numbers."""

    model: str  # the model that gave the second opinion
    numbers: List[str] = field(default_factory=list)  # every number the second answer states (answer_numbers)
    disagreed: List[str] = field(default_factory=list)  # the first answer's numbers it contradicts
    instead: List[str] = field(default_factory=list)  # its own numbers that contradict them

    @property
    def agreed(self) -> bool:
        return not self.disagreed

    def as_dict(self) -> Dict[str, Any]:
        return {"model": self.model, "agreed": self.agreed, "numbers": list(self.numbers),
                "disagreed": list(self.disagreed), "instead": list(self.instead)}


async def second_opinion(complete: Callable[..., Any], messages: List[Dict[str, str]], models: Sequence[str],
                         first: Sequence[Number], asked: str, grade: Callable[[str], str],
                         timeout: Optional[float]) -> Optional[SecondOpinion]:
    """Ask `models` the same messages and compare the numbers; None when there is nothing to compare.

    `complete` is the client's non-streamed call, so the second answer is never
    written over the first on the page. `grade` turns a reply into the answer
    text ("" for a refusal). A failed or late call, a refusal, or an answer with
    no numbers gives None: a second model that can't answer has no opinion on
    the first one's numbers.
    """
    try:
        reply = await asyncio.wait_for(complete(messages, models=list(models)), timeout=timeout)
    except (LLMError, asyncio.TimeoutError) as exc:
        log.warning("number agreement check failed (%s); keeping the answer as it is", exc.__class__.__name__)
        return None
    text = grade(reply.text)
    numbers = answer_numbers(text, asked) if text else []
    if not numbers:
        log.info("number agreement: %s %s, no opinion", reply.model, "gave no numbers" if text else "refused")
        return None
    disagreed, instead = disagreeing(first, numbers)
    opinion = SecondOpinion(reply.model, [raw for _, _, raw in numbers], disagreed, instead)
    log.info("number agreement with %s: %s", reply.model,
             f"disagrees, flagging {', '.join(disagreed)} (it says {', '.join(instead)})" if disagreed else "agrees")
    return opinion
