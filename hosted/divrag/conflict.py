"""When documents disagree: name every document's value, with its level, and a labelled recommendation (DAR-674).

Dr. Namian (Nov 17): when manuals contradict each other, show both sources and
a recommendation, and never hide either value. The one real case seen
(locked wztc-075): asked for the MUTCD's buffer length at 50 mph (Table 6B-2,
425 ft), a free model answered 240 ft from NCDOT's own buffer table, cited.

After the answer is final, when it states numbers and its passages come from
two or more documents, one more model call reads the passages
(CONFLICT_PROMPT): for each document, the value it gives for the case the
question asks, and a recommendation. Whether they disagree is decided here,
not by the model: each value must be in its passage (verify.py), and at least
two documents must give two different values. The model is not shown the
answer: asked whether the documents disagree "with the answer", the free
models only repeated the answer's document and value. The answer then ends
with a block that lists each value with its document's level (register.py),
title and citation, and the recommendation, labelled as one: the model's
judgment, or, when DOCUMENT_PRECEDENCE is set, what that order says.

The check can only compare what retrieval brought. In wztc-075 the Table 6B-2
rows never reach the passages (the MUTCD prints "6B‑2" with a non-breaking
hyphen, so the table's keyword field reads "Table 6B"); with them added, the
free model lists 425 ft (Federal) against 240 ft (State).

Only answers with numbers are checked: "different values for the same thing"
is what the ticket asks for, and a call on every answer would double the cost
of the many answers whose passages span documents. A disagreement about a
requirement in words is not caught.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from .agreement import answer_numbers
from .divisions import document_for
from .index_file import Hit
from .numbers import normalize
from .register import REGISTER, Register
from .verify import unverified_numbers

log = logging.getLogger(__name__)

NO_CONFLICT = "NO_CONFLICT"
MAX_VALUE_CHARS = 200
MAX_RECOMMENDATION_CHARS = 600

CONFLICT_SYSTEM = """You compare passages from federal and North Carolina Department of Transportation (NCDOT) documents. Use only the passages."""

CONFLICT_PROMPT = """Question: {question}

Passages, each with its document's level (Federal, State, Division or Internal):

{context}

Documents in these passages: {documents}.

Go through these documents one at a time. For each, find the value its passages give for exactly the case the question asks about (the same quantity, speed, road type and conditions). A passage gives that value when it states it for that purpose, or when it is in a table that a passage or the question says is to be used for that purpose.

Reply with only this JSON, one entry for every document listed above, in that order:
{{"values": [{{"document": "<document title>", "passage": <number of the passage that gives the value, or null>, "value": "<the value with its unit, as the passage writes it, or null when the document gives none>"}}, ...], "recommendation": "<when two documents give different values: one or two sentences on which value the reader should follow and why, from what the passages say about their scope, authority and edition, citing passages as [n]; otherwise empty>"}}"""

# One model call: (messages, models) -> the reply (llm.Completion).
Complete = Callable[..., Awaitable[Any]]
_JSON = re.compile(r"\{.*\}", re.DOTALL)
# For a reply that is not quite JSON (Nemotron 3.5 Super put the recommendation inside the values list):
# each flat {...} object, and the recommendation string, read on their own.
_OBJECT = re.compile(r"\{[^{}]*\}")
_RECOMMENDATION = re.compile(r'"recommendation"\s*:\s*"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Value:
    n: int  # the passage's number in the answer's passages (1-based)
    value: str
    file: str
    title: str
    level: Optional[str]
    level_label: Optional[str]


@dataclass
class Conflict:
    values: List[Value]
    recommendation: str
    by: str = "model"  # "model": the model's judgment; "precedence": DOCUMENT_PRECEDENCE
    model: Optional[str] = None  # the model that compared the passages

    def block(self) -> str:
        """The lines added after the answer, citing passages by their numbers in the answer's passages."""
        lines = ["**The documents give different values:**"]
        for v in self.values:
            who = f"{v.level_label}, {v.title}" if v.level_label else v.title
            lines.append(f"- {who}: {v.value} [{v.n}]")
        label = ("**Recommendation** (from the configured document precedence, not a reading of the passages):"
                 if self.by == "precedence" else "**Recommendation** (the assistant's judgment, not an NCDOT rule):")
        return "\n".join(lines) + f"\n\n{label} {self.recommendation}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "values": [{"value": v.value, "title": v.title, "level": v.level, "level_label": v.level_label}
                       for v in self.values],
            "recommendation": self.recommendation,
            "by": self.by,
            "model": self.model,
        }


def documents(hits: Sequence[Hit]) -> str:
    """The passages' documents, by level and title, in order of first passage: what the prompt asks about one by one."""
    seen: List[str] = []
    for hit in hits:
        file = hit.chunk.get("source") or ""
        if file and file not in seen:
            seen.append(file)
    out = []
    for file in seen:
        document = document_for(file)
        entry = REGISTER.entry(file)
        title = document.title if document else file
        out.append(f"{REGISTER.label(entry.level)} · {title}" if entry else title)
    return "; ".join(out)


def worth_checking(text: str, hits: Sequence[Hit], asked: str) -> bool:
    """The answer states a number that answers the question and its passages come from two or more documents."""
    files = {part.get("source") for hit in hits for part in hit.chunk.get("parts", [hit.chunk])}
    return len(files - {None, ""}) >= 2 and bool(answer_numbers(text, asked))


def _values(raw: Any, hits: Sequence[Hit], passage_text: Callable[[Dict], str],
            register: Register) -> List[Value]:
    """The reply's values that hold up: a real passage, a short value that is in that passage, one per document."""
    values: List[Value] = []
    seen_files = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        n, value = item.get("passage"), " ".join(str(item.get("value") or "").split())
        if isinstance(n, str) and n.strip(" []").isdigit():  # "4" or "[4]"
            n = int(n.strip(" []"))
        if not isinstance(n, int) or not 1 <= n <= len(hits) or not value or len(value) > MAX_VALUE_CHARS:
            continue
        chunk = hits[n - 1].chunk
        file = chunk.get("source") or ""
        if file in seen_files:
            continue
        # The value must be read from its passage: a number the passage doesn't hold is the model's, not the document's.
        if unverified_numbers(value, [passage_text(chunk)]):
            log.info("conflict check: passage %d does not hold %r; dropped", n, value)
            continue
        document = document_for(file)
        entry = register.entry(file)
        level = entry.level if entry else None
        values.append(Value(n=n, value=value, file=file, title=document.title if document else file,
                            level=level, level_label=register.label(level)))
        seen_files.add(file)
    return values


def _salvage(text: str) -> Optional[Dict[str, Any]]:
    """The values and recommendation of a reply that is almost JSON, or None when it has no value objects."""
    values = []
    for match in _OBJECT.finditer(text):
        try:
            item = json.loads(match.group(0))
        except ValueError:
            continue
        if isinstance(item, dict) and "value" in item:
            values.append(item)
    if not values:
        return None
    recommendation = _RECOMMENDATION.search(text)
    try:
        advice = json.loads(f'"{recommendation.group(1)}"') if recommendation else ""
    except ValueError:
        advice = ""
    return {"values": values, "recommendation": advice}


def parse(reply: str, hits: Sequence[Hit], passage_text: Callable[[Dict], str],
          register: Register = REGISTER) -> Optional[Conflict]:
    """The disagreement in the model's reply, or None when there is none that holds up."""
    text = (reply or "").strip()
    if not text or text.startswith(NO_CONFLICT):
        return None
    match = _JSON.search(text)
    try:
        data = json.loads(match.group(0)) if match else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = _salvage(text)
    if data is None:
        log.info("conflict check: unreadable reply; no disagreement shown")
        return None
    values = _values(data.get("values"), hits, passage_text, register)
    if len({v.file for v in values}) < 2 or len({normalize(v.value) for v in values}) < 2:
        return None
    recommendation = " ".join(str(data.get("recommendation") or "").split())
    if len(recommendation) > MAX_RECOMMENDATION_CHARS:
        recommendation = recommendation[:MAX_RECOMMENDATION_CHARS].rsplit(" ", 1)[0] + " …"
    if not recommendation:
        recommendation = "Check both documents; neither value is shown as the one to follow."
    return Conflict(values=values, recommendation=recommendation)


def by_precedence(conflict: Conflict, precedence: Sequence[str], register: Register = REGISTER) -> Conflict:
    """The conflict with the recommendation DOCUMENT_PRECEDENCE gives, when it picks one level; unchanged otherwise.

    Levels not listed rank below every listed one. When the best-ranked level
    is shared by values from two documents, the order can't choose, and the
    model's recommendation stays.
    """
    if not precedence:
        return conflict

    def rank(v: Value) -> int:
        return precedence.index(v.level) if v.level in precedence else len(precedence)

    best = min(rank(v) for v in conflict.values)
    winners = [v for v in conflict.values if rank(v) == best]
    if best == len(precedence) or len(winners) != 1:
        return conflict
    order = ", then ".join(register.label(level) or level for level in precedence)
    v = winners[0]
    text = f"follow the {v.level_label} document, {v.title}: {v.value} [{v.n}]. The order is {order}."
    return Conflict(values=conflict.values, recommendation=text[0].upper() + text[1:], by="precedence",
                    model=conflict.model)


async def check(complete: Complete, question: str, hits: Sequence[Hit], context: str,
                passage_text: Callable[[Dict], str], timeout: Optional[float],
                precedence: Sequence[str] = (), register: Register = REGISTER) -> Optional[Conflict]:
    """Ask the model for each document's value; the checked disagreement, or None (also when the call fails).

    `context` is the passages as numbered in the answer, with their levels.
    """
    messages = [
        {"role": "system", "content": CONFLICT_SYSTEM},
        {"role": "user", "content": CONFLICT_PROMPT.format(question=question, context=context,
                                                            documents=documents(hits))},
    ]
    try:
        reply = await asyncio.wait_for(complete(messages), timeout=timeout)
    except Exception as exc:  # noqa: BLE001  a failed check costs the check, never the answer
        log.warning("conflict check failed (%s); answering without it", exc.__class__.__name__)
        return None
    conflict = parse(reply.text, hits, passage_text, register)
    if conflict is None:
        return None
    conflict.model = reply.model
    log.info("conflict check by %s: %d documents disagree", reply.model, len(conflict.values))
    return by_precedence(conflict, precedence, register)
