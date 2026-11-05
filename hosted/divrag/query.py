"""What a question names explicitly: table, figure and section numbers, document codes (DAR-657).

Deterministic regexes, no model. "What does Table 3 in the TMP Design Manual
give for a 40 mph design speed?" names Table 3; the retriever
counts those identifiers more in the keyword index's caption/ID field, as a
soft boost (never a filter), and the vector search still gets the question as
asked. The vocabulary is closed (the manuals' own labels), so a regex is
enough and a wrong guess only shifts a score.
"""

import re
from dataclasses import dataclass
from typing import List, Tuple

# "Table 3-2", "Tbl. 6H-3", "Fig 2-1", "Figure C11.5.6-3", "Exhibit 4", "Section 4.2", "Sec. 3.6.4.1",
# "Sheet 1", "Standard 1101.01", "Std. 1101.01", also "Table No. 3". The number may start with a
# letter (MUTCD "6H-3", appendix "A-3") and end with one ("5-1b"); a trailing dot is not part of it.
_LABELS = {"table": "Table", "tbl": "Table", "figure": "Figure", "fig": "Figure", "exhibit": "Exhibit",
           "section": "Section", "sec": "Section", "sheet": "Sheet", "standard": "Standard", "std": "Standard"}
ID_PATTERN = re.compile(
    r"\b(?P<label>table|tbl|figure|fig|exhibit|section|sec|sheet|standard|std)\.?\s+(?:no\.?\s*)?"
    r"(?P<id>[a-z]?[0-9]+[a-z]?(?:[-.][0-9]+[a-z]?)*|[a-z](?:[-.][0-9]+[a-z]?)+)(?![a-z0-9])",
    re.IGNORECASE)
# Document codes: NCDOT's "04-20340" and leading-zero numbers ("04091", "010604"), or a 4-6 digit
# number right after a word that says it is one ("document 20340"). A bare "6000" is an ADT or a
# year far more often than a code in these manuals, so it is left to the body search.
_CODE = re.compile(
    r"\b(?P<dashed>[0-9]{2}-[0-9]{5})\b|(?<![0-9.])(?P<zero>0[0-9]{3,5})\b"
    r"|\b(?:(?:document|doc|form|drawing|detail|number)\.?|no\.)\s*#?\s*(?P<named>[0-9]{4,6})\b|#\s*(?P<hash>[0-9]{4,6})\b",
    re.IGNORECASE)


def id_name(match: "re.Match[str]") -> str:
    """An ID_PATTERN match in one spelling ("tbl. 6h-3" -> "Table 6H-3"). index_file.field_text writes the
    field's IDs the same way, so the caption/ID field and the question name a table alike."""
    return f"{_LABELS[match.group('label').lower()]} {match.group('id').upper()}"


@dataclass(frozen=True)
class ParsedQuery:
    ids: List[str]        # "Table 3-2", "Figure 5", "Section 4.2": label spelled out, number upper-cased
    doc_codes: List[str]  # "04091", "04-20340"


def parse(question: str) -> ParsedQuery:
    """The identifiers and document codes the question names, each once, in order of appearance."""
    ids: List[str] = []
    codes: List[str] = []
    spans: List[Tuple[int, int]] = []
    for match in ID_PATTERN.finditer(question):
        _add(ids, id_name(match))
        spans.append(match.span())
    for match in _CODE.finditer(question):
        group = match.lastgroup  # the one alternative that matched: dashed, zero, named or hash
        if any(a <= match.start(group) < b for a, b in spans):
            continue  # the number of "Standard 04091"-style labels is already an id
        _add(codes, match.group(group))
        spans.append(match.span(group))
    return ParsedQuery(ids, codes)


def _add(items: List[str], item: str) -> None:
    if item not in items:
        items.append(item)
