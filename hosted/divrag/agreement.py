"""A second model's opinion on the numbers of an answer (DAR-663).

The number check (verify.py, DAR-659) flags a number the cited passages don't
contain. It cannot flag a number read from the wrong cell of the right table:
on the locked split 8 of 232 answers were confident and wrong, and in all 8 the
wrong number was printed on the cited page (the model read the wrong row or
column; with 8 passages, a first answer on the tuning split read the wrong row
of Detail 3-2A, docs/redo-decision-log.md D15). A second model reading the same
passages for the same question seldom misreads the same cell, so when the two
answers state different numbers, the first answer's numbers that the second
doesn't state are returned to be flagged as unverified.

What is compared is the numbers that answer the question. Left out are:

- citation markers, list markers, ordinals and clock times (verify's rules);
- page references ("p.13 (PDF page 37)", rule 8 of the prompt asks for them);
- identifiers ("Table 6-1", "Detail 3-2A", "Section 3.6"): one model naming
  the table and the other not is no disagreement about its value;
- numbers the question (or an earlier question) gave, as the number check
  leaves them out: "at 40 mph" repeats the visitor.

The two answers disagree only when each states a number the other doesn't. An
answer that states fewer numbers (the second leaves out a context number, or
the first adds the metric conversion) is an omission, not a contradiction, and
flagging it would only add false alarms. Numbers are compared with numbers.py's
normalization: 12-foot and 12 ft are one number, and a bare 27.42 matches
27.42 ft, while 5 ft and 5 in differ.

The second model is the next free model of the configured chain after the one
that answered, never the same one (it would repeat its own misread) and never a
paid one: when OpenAI answered (FallbackClient), the second opinion comes from
the first free model, so the check never spends OpenAI money twice.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .llm import LLMError
from .numbers import TOLERANCE, numbers_with_units
from .verify import _stated

log = logging.getLogger(__name__)

# Only these models may give the second opinion (config.FREE_SUFFIX): the check doubles
# the model calls of a numeric answer, and it must never double a paid one.
FREE_SUFFIX = ":free"

Number = Tuple[float, Optional[str], str]

# "PDF page 37", "p.13", "pp. 12-13", "pages 36 to 38": where a value is, not the value.
_PAGE_REF = re.compile(
    r"\b(?:pdf\s+)?(?:pages?|pp?\.)\s*\d+[a-z]?(?:\s*(?:[-–]|to|and)\s*\d+[a-z]?)?", re.IGNORECASE)
# "Table 6-1", "Detail 3-2A", "Section 3.6", "Std. No. 1101.02": the name of a table or rule, not a value read from it.
_IDENTIFIER = re.compile(
    r"\b(?:tables?|figures?|figs?\.|details?|sections?|sect\.|chapters?|parts?|appendix|appendices|standards?|"
    r"std\.|drawings?|exhibits?|articles?|notes?|items?|steps?|types?|class(?:es)?|categor(?:y|ies)|groups?|"
    r"levels?|cases?|options?|rows?|columns?|rules?|forms?|sheets?|plates?|vol\.|volumes?)"
    r"\s*(?:no\.\s*)?[a-z]?\d+(?:[.\-–]\d+)*[a-z]?\b",
    re.IGNORECASE)


def _same(a: Number, b: Number) -> bool:
    """One value, with the same unit when both carry one (a table cell rarely repeats its column's unit)."""
    return abs(a[0] - b[0]) <= TOLERANCE and (a[1] is None or b[1] is None or a[1] == b[1])


def answer_numbers(text: str, asked: str = "") -> List[Number]:
    """The numbers in an answer that answer the question, once each, in order (see the module notes)."""
    given = numbers_with_units(asked)
    cleaned = _IDENTIFIER.sub(" ", _PAGE_REF.sub(" ", _stated(text)))
    found: List[Number] = []
    for number in numbers_with_units(cleaned):
        if any(_same(number, g) for g in given) or any(_same(number, f) and number[1] == f[1] for f in found):
            continue
        found.append(number)
    return found


def disagreeing(first: Sequence[Number], second: Sequence[Number]) -> List[str]:
    """The first answer's numbers to flag: those the second doesn't state, when it states one the first doesn't.

    [] when they agree, or when one answer only leaves numbers out.
    """
    first_only = [a for a in first if not any(_same(a, b) for b in second)]
    second_only = [b for b in second if not any(_same(b, a) for a in first)]
    if not (first_only and second_only):
        return []
    return list(dict.fromkeys(raw for _, _, raw in first_only))


def second_opinion_models(llm: Any, used: str) -> List[str]:
    """The free models to ask for a second opinion after `used` answered, in the order to try; [] when there is none.

    The models after `used` in the configured chain come first, then the ones
    before it, so the last model's answer is checked by the first. A model name
    the chain doesn't know is taken to be the first model's (OpenRouter names
    the model that answered; it is the first unless it fell back).
    """
    chain = list(getattr(llm, "models", None) or llm.retry_models(used))
    if used in chain:
        at = chain.index(used)
        ordered = chain[at + 1:] + chain[:at]
    else:
        ordered = chain[1:] + chain[:1]
    return [m for m in dict.fromkeys(ordered) if m != used and m.endswith(FREE_SUFFIX)]


@dataclass
class SecondOpinion:
    """What the second model's answer said about the first answer's numbers."""

    model: str  # the model that gave the second opinion
    numbers: List[str] = field(default_factory=list)  # the numbers the second answer states (answer_numbers)
    disagreed: List[str] = field(default_factory=list)  # the first answer's numbers it contradicts (disagreeing)

    @property
    def agreed(self) -> bool:
        return not self.disagreed

    def as_dict(self) -> Dict[str, Any]:
        return {"model": self.model, "agreed": self.agreed, "numbers": list(self.numbers),
                "disagreed": list(self.disagreed)}


async def second_opinion(complete: Callable[..., Any], messages: List[Dict[str, str]], models: Sequence[str],
                         first: Sequence[Number], asked: str, grade: Callable[[str], str],
                         timeout: Optional[float]) -> Optional[SecondOpinion]:
    """Ask `models` the same messages and compare the numbers; None when there is nothing to compare.

    `complete` is the client's non-streamed call: the visitor keeps reading the
    first answer while the second is written, so it is never streamed over it.
    `grade` turns a reply into the answer text ("" for a refusal). A failed or
    late call, a refusal, or an answer with no numbers gives None: a second
    model that can't answer has no opinion on the first one's numbers.
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
    opinion = SecondOpinion(reply.model, [raw for _, _, raw in numbers], disagreeing(first, numbers))
    log.info("number agreement with %s: %s", reply.model,
             f"disagrees, flagging {', '.join(opinion.disagreed)} (it says {', '.join(opinion.numbers)})"
             if opinion.disagreed else "agrees")
    return opinion
