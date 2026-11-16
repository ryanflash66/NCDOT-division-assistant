"""The row-label check (DAR-664): a number read from the wrong row of a cited table.

The number check (verify.py) only asks whether a number is somewhere in the
cited passages. The free models sometimes take the right table and the wrong
row: asked for the runout length at 60 mph and an ADT of 800 to 2,000 (Detail
3-2A, tuning item tmsd-003), one answered with a neighbouring row's value and a
correct citation, so the number was in the passage and nothing flagged it.

This check looks at the rows that hold the answer's number. When the question
names a row label (a number such as the offset 14, or, in labelled rows, a word
such as "Maximum Deflection") and none of those rows carries it, while another
row of the same table does, the answer is flagged. It stays quiet whenever it
cannot tell: no table row in the cited passages, the number in no row's data
cells, a table it cannot split into label and data cells, or an answer number
the question itself gave.

Two table shapes are read, both written by the index build (docs/table-quality.md):
Markdown pipe rows, and the labelled rows that follow a "Rows:" line, e.g.

    Offset (ft)=14 | Maximum Deflection | Design Speed(mph): 30=25.16, 40=27.42

Label cells are the cells up to the last text cell of a pipe row (the first
cell when every cell is a number), and the part before the last " | " of a
labelled row; the rest are data cells. Words are compared only in labelled rows:
a pipe table's header rows look like data rows ("**Offset (ft)**|**Maximum
Deflection (in)**|**30**|**40**") and would otherwise outscore the real row on
words alone.
"""

import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from .numbers import TOLERANCE, numbers_with_units
from .verify import _stated

_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}")
_ROWS_HEADER = re.compile(r"^\s*Rows(?:\s*\(.*\))?:\s*$")
# A cell that is only a number, a range or a number with a unit ("27.42", "400-1,500", "5 ft").
_NUMBER_CELL = r"\d[\d.,/]*\s*(?:ft|in|mph|%|deg|\"|')?"
_NUMERIC_CELL = re.compile(rf"^{_NUMBER_CELL}(?:\s*(?:-|–|to)\s*{_NUMBER_CELL})?$", re.IGNORECASE)
# A reference to a numbered thing, not a value to look for in a row label: "Detail 3-2A", "Table 4-1", "page 37".
_IDENTIFIER = re.compile(r"\b(?:table|figure|fig|detail|section|sec|page|pages|pg|chapter|part|std|no|item|"
                         r"sheet|sheets|rule|note|article|appendix)\b\.?\s*#?\s*[\w.\-–]+", re.IGNORECASE)
_WORD = re.compile(r"[a-z]{3,}")
_STOPWORDS = frozenset("""
    the and for are was were what which who whom whose when where why how does did has have had can could will would
    should must may might shall this that these those there their them they then than with without from into onto over
    under about above below between per each any all both either neither not only also its his her our your you
    give gives given state states stated say says said list lists tell show shows apply applies applied required
    require requires requirement need needs needed use used using value values number numbers amount much many
    according manual document documents division asked ask question answer please
    ft mph inch inches feet foot percent
""".split())


def _words(text: str) -> Set[str]:
    out = set()
    for word in _WORD.findall(text.lower()):
        if word in _STOPWORDS:
            continue
        out.add(word[:-2] if word.endswith("es") and len(word) > 5 else word[:-1] if word.endswith("s") and len(word) > 4 else word)
    return out


def _values(text: str) -> List[float]:
    return [value for value, _, _ in numbers_with_units(text)]


class _Row:
    def __init__(self, label: str, data: List[str], labelled: bool, first: str = ""):
        self.label = label
        self.first = first  # the first cell, for a blank first cell in the next pipe row
        self.data = data  # the data cells, as text
        self.labelled = labelled
        self.label_numbers = _values(label)
        self.label_words = _words(label)
        self.data_numbers = [(v, u) for text in data for v, u, _ in numbers_with_units(text)]

    def holds(self, value: float, unit: Optional[str]) -> bool:
        return any(abs(value - v) <= TOLERANCE and (unit is None or u is None or unit == u)
                   for v, u in self.data_numbers)


def _pipe_row(line: str, above: str = "") -> Optional[_Row]:
    """A pipe row; a blank first cell takes the one above it (a row label spanning rows, as in "Offset 14" / two measures)."""
    # One outer pipe each side only: a blank first cell is "||", which strip("|") would swallow.
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") else body
    cells = [c.replace("**", "").strip() for c in body.split("|")]
    if len(cells) < 2:
        return None
    if not cells[0]:
        cells[0] = above
    numeric = [bool(c) and bool(_NUMERIC_CELL.match(c)) for c in cells]
    text_cells = [i for i, (c, n) in enumerate(zip(cells, numeric)) if c and not n]
    last_label = text_cells[-1] if text_cells else 0
    if last_label >= len(cells) - 1:
        return None  # no data cell after the label cells: not a row we can read
    return _Row(" ".join(cells[: last_label + 1]), cells[last_label + 1:], labelled=False, first=cells[0])


_DATA_SEGMENT = re.compile(r"^[^=|]*:\s*\S[^|]*=")


def _labelled_row(line: str) -> Optional[_Row]:
    segments = [s.strip() for s in line.split(" | ")]
    if len(segments) < 2 or not _DATA_SEGMENT.match(segments[-1]):
        return None
    pairs = re.findall(r"=\s*([^,=]+)", segments[-1])
    label = " ".join(s.replace("=", " ") for s in segments[:-1])
    return _Row(label, [p.strip() for p in pairs], labelled=True) if pairs else None


def _tables(passage: str) -> List[List[_Row]]:
    """The rows of each table in a passage text: a block of pipe rows, or the labelled rows after "Rows:"."""
    tables: List[List[_Row]] = []
    current: List[_Row] = []
    kind = None  # "pipe" or "rows"
    above = ""

    def close() -> None:
        nonlocal current, kind, above
        if current:
            tables.append(current)
        current, kind, above = [], None, ""

    for line in passage.splitlines():
        stripped = line.strip()
        if _ROWS_HEADER.match(stripped):
            close()
            kind = "rows"
        elif kind == "rows":
            row = _labelled_row(stripped) if stripped else None
            if row is None:
                close()
            else:
                current.append(row)
        elif stripped.startswith("|"):
            if _SEPARATOR.match(stripped):
                # The rows above the separator are the header: their number cells (the 30 and 40 mph
                # columns) are labels, and must not pass for data cells that hold an answer's number.
                current.clear()
                continue
            kind = "pipe"
            row = _pipe_row(stripped, above)
            if row is not None:
                current.append(row)
                above = row.first
        elif kind == "pipe":
            close()
    close()
    return tables


def _question_terms(question: str) -> Tuple[Set[float], Set[str]]:
    text = _IDENTIFIER.sub(" ", question)
    return set(_values(text)), _words(text)


def _hits(row: _Row, numbers: Set[float], words: Set[str]) -> Tuple[int, int]:
    n = sum(1 for q in numbers if any(abs(q - v) <= TOLERANCE for v in row.label_numbers))
    w = len(words & row.label_words) if row.labelled else 0
    return n, w


def _misread(value: float, unit: Optional[str], tables: Sequence[List[_Row]], numbers: Set[float],
             words: Set[str]) -> Optional[bool]:
    """True when the rows holding the number all lack a label the question names that another row has.

    None when there is nothing to judge (no table holds the number).
    """
    verdicts = []
    for rows in tables:
        holding = [r for r in rows if r.holds(value, unit)]
        if not holding:
            continue
        have = max(_hits(r, numbers, words) for r in holding)
        others = [_hits(r, numbers, words) for r in rows if r not in holding]
        # More of the question's numbers, or as many and more of its words (labelled rows only).
        better = any(n > have[0] or (n == have[0] and w > have[1]) for n, w in others)
        verdicts.append((rows[0].labelled, better))
    if not verdicts:
        return None
    # The labelled rows of a table say more than its pipe rows (blank label cells filled, words comparable),
    # so they decide when the table has both.
    decisive = [better for labelled, better in verdicts if labelled] or [better for _, better in verdicts]
    return all(decisive)


def misread_numbers(answer: str, passages: Iterable[str], question: str) -> List[str]:
    """The answer's numbers that sit in a table row the question's labels don't point to, normalized, once each.

    `passages` are the cited passages' texts; `question` is the question with
    the earlier turns' questions (numbers the visitor gave are never flagged).
    """
    tables = [rows for passage in passages for rows in _tables(passage)]
    if not tables:
        return []
    numbers, words = _question_terms(question)
    given = [v for v, _, _ in numbers_with_units(question)]
    flagged: List[str] = []
    for value, unit, raw in numbers_with_units(_stated(answer)):
        if any(abs(value - g) <= TOLERANCE for g in given):
            continue
        if _misread(value, unit, tables, numbers, words) and raw not in flagged:
            flagged.append(raw)
    return flagged
