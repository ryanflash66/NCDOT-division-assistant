"""Two readings of each picture page, and what to do when they disagree (DAR-739).

A scanned, sideways or drawing page reaches the index as text OCR or the PDF's
picture text pulled out of it, and on those pages the text can be wrong in ways
the model can't see. Dr. Namian's example (Nov 17): a permit prints "1 1/2 in."
and OCR reads "1/½2" (utilities-h056); a sideways table's rows come out right
to left, so 200 ft sits where the 150 ft bay taper should (tmsd-h052).

So prototype.read_pages asks OpenAI to transcribe each such page from its image
once, at indexing time, and stores that reading beside the index
(page_readings.json) with an agreement flag from compare():

    agree       the two readings have the same numbers (with units), and every
                table row the image reading has comes out in the same order in
                the OCR text when it is there
    disagree    a number one reading has and the other lacks, a unit that
                differs, or a table row whose numbers come out in another order
                (the sideways tables); `differences` holds what to show, "X vs Y"
    image_only  OCR found no text on the page

At answer time (Readings.annotate) a passage from a `disagree` or `image_only`
page carries its page's image reading, and the model is told to take values from
it where the two differ (it was right on the DAR-733 pages). The model reads only
the lines of the reading that hold a differing value (excerpt()), once per page
in a prompt: the whole reading with every passage cost 1.8 s of median answer
time on the development set (Nov 25), and the values that fixed the misreads
are on those lines. The image reading
is not trusted alone either: every cited page that disagrees gets a notice
naming the two readings, and the Sources panel shows both. Pages that agree
change nothing, in the prompt or the reply.

compare() looks at numbers and units only. Words differ between the two readings
all the time (OCR noise, the model's Markdown), and it is a wrong number that
gives a wrong answer.
"""

import difflib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .index_file import Hit
from .numbers import normalize

log = logging.getLogger(__name__)

READINGS_FILE = "page_readings.json"
AGREE, DISAGREE, IMAGE_ONLY = "agree", "disagree", "image_only"
FLAGS = (AGREE, DISAGREE, IMAGE_ONLY)
# Differences kept per page in page_readings.json, and shown in one notice.
MAX_DIFFERENCES = 8
NOTICE_DIFFERENCES = 2
# One side of a difference that the other reading has no counterpart for.
MISSING = "(missing)"
# Words the notice shows either side of the answer's number in a long difference.
NOTICE_WORDS = 5
# Words either side of a differing number in an "X vs Y" snippet.
SNIPPET_WORDS = 3
# A table row: a line of the image reading with at least this many numbers.
ROW_NUMBERS = 3
# The image reading the model reads for a page with no OCR text at all, where it is the
# page's only text. A page's whole reading averages about 1,700 characters (the OCR text of
# the 1,189 flagged pages: mean 1,656, median 1,427), and a few dense drawings run to 20,000;
# past this the reading is cut with a mark.
PASSAGE_READING_CHARS = 6000
# The part of a disagreeing page's image reading the model reads (excerpt()): the lines
# holding a differing value, EXCERPT_CONTEXT_LINES lines either side and the header row of
# a table they are in, cut at EXCERPT_CHARS. The whole reading (median 1,268 characters,
# p90 2,822) went with every passage from the page until Nov 25.
EXCERPT_CHARS = 1500
EXCERPT_CONTEXT_LINES = 1
# The reading's first lines, kept in every excerpt: the page's running head and title.
EXCERPT_TITLE_LINES = 2
EXCERPT_GAP = "…"
# The image reading the Sources panel shows under the OCR excerpt.
SOURCE_READING_CHARS = 1500

READING_HEADER = "Read from the page image (PDF page {page}), because the text above may be misread:"
READING_RULE = (
    "Some passages end with text \"Read from the page image\": the same page transcribed from its image, because "
    "the text extracted from the page looked wrong (a scan, a sideways table or a drawing). Where the two differ, "
    "take the value from the image reading, and cite the passage's number as usual."
)
NOTICE = ("{where} is from a low-quality scan; the two readings differ ({pairs}). "
          "Check the page before relying on this value.")
NOTICE_NO_TEXT = ("{where} is from a low-quality scan; the text could only be read from the page image. "
                  "Check the page before relying on this value.")

# Markup that is not on the printed page: pymupdf4llm's comments and picture-text marks,
# Markdown emphasis and headings, table bars, and the "OCR text (...)" lines rag.ocr adds.
_MARKUP = re.compile(r"<!--.*?-->|</?[a-z][^>]*>|\*\*|__|^#{1,6}\s*|^OCR text \([^)\n]*\):", re.MULTILINE | re.DOTALL)
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}.*$", re.MULTILINE)
# A number with its unit in normalized text (numbers.normalize spells units "ft", "in", "mph", "%", "deg").
_TOKEN = re.compile(r"\d+(?:\.\d+)?(?:\s(?:ft|in|mph|%|deg)(?![a-z%]))?|[a-z]+")
_NUMBER = re.compile(r"^(\d+(?:\.\d+)?)(?:\s(ft|in|mph|%|deg))?$")


Number = Tuple[float, Optional[str]]


def clean(text: str) -> str:
    """The text without markup, so both readings are compared on what the page prints."""
    text = _TABLE_RULE.sub(" ", _MARKUP.sub(" ", text or ""))
    return text.replace("|", " ")


def _tokens(text: str) -> List[str]:
    return _TOKEN.findall(normalize(clean(text)))


def _number(token: str) -> Optional[Number]:
    match = _NUMBER.match(token)
    return (float(match.group(1)), match.group(2)) if match else None


def _numbers(tokens: Iterable[str]) -> List[Number]:
    return [n for n in (_number(t) for t in tokens) if n]


def _unmatched(ours: Sequence[Number], theirs: Sequence[Number]) -> List[Number]:
    """Our numbers the other reading has nowhere on the page (a value it lacks, or the same value in another unit).

    Presence, not counts: the OCR text of a page is its chunks' text, and chunks
    overlap, so a number there can come twice. A number without a unit matches
    the same value with one (OCR drops a foot mark more often than it misreads one).
    """
    exact = set(theirs)
    values = {value for value, _ in theirs}
    unitless = {value for value, unit in theirs if unit is None}
    out = []
    for number in dict.fromkeys(ours):
        value, unit = number
        if number in exact or (unit is None and value in values) or (unit is not None and value in unitless):
            continue
        out.append(number)
    return out


def _row_numbers(text: str) -> List[List[float]]:
    """The values of each line with ROW_NUMBERS or more numbers, in order: a table row."""
    rows = []
    for line in clean(text).splitlines():
        values = [value for value, _ in _numbers(_tokens(line))]
        if len(values) >= ROW_NUMBERS:
            rows.append(values)
    return rows


def _number_text(value: float) -> str:
    return f"{value:g}" if value != int(value) else str(int(value))


def _snippet(tokens: Sequence[str], start: int, end: int) -> str:
    lo, hi = max(0, start - SNIPPET_WORDS), min(len(tokens), end + SNIPPET_WORDS)
    return " ".join(tokens[lo:hi])


def _value_differences(ocr: List[str], image: List[str], wanted: set) -> List[Tuple[str, str]]:
    """'X vs Y' snippets around the numbers in `wanted`, from where the two token lists stop matching."""
    out: List[Tuple[str, str]] = []
    matcher = difflib.SequenceMatcher(None, ocr, image, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        numbers = set(_numbers(ocr[i1:i2])) | set(_numbers(image[j1:j2]))
        if numbers & wanted:
            out.append((_snippet(ocr, i1, i2) if i2 > i1 else MISSING,
                        _snippet(image, j1, j2) if j2 > j1 else MISSING))
            wanted -= numbers
        if not wanted:
            break
    for value, unit in sorted(wanted, key=lambda n: (n[0], n[1] or "")):
        # A number the alignment didn't reach: name it alone.
        shown = _number_text(value) + (f" {unit}" if unit else "")
        out.append((MISSING, shown))
    return out


def compare(ocr_text: str, image_text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """The agreement flag of a page's two readings, and up to MAX_DIFFERENCES (OCR, image) snippets."""
    ocr, image = _tokens(ocr_text), _tokens(image_text)
    if not ocr:
        return IMAGE_ONLY, []
    ocr_numbers, image_numbers = _numbers(ocr), _numbers(image)
    wanted = set(_unmatched(image_numbers, ocr_numbers)) | set(_unmatched(ocr_numbers, image_numbers))
    differences = _value_differences(ocr, image, set(wanted)) if wanted else []
    # A sideways table keeps its numbers but loses their order (tmsd-h052: 200' 575' 250' 55 60
    # for a row that prints 60 55 250' 575' 200'), so a row of the image reading whose numbers
    # are an OCR line's in another order is a difference too.
    ocr_rows = _row_numbers(ocr_text)
    for row in _row_numbers(image_text):
        same = [r for r in ocr_rows if Counter(r) == Counter(row)]
        if same and row not in same:
            differences.append((", ".join(map(_number_text, same[0])), ", ".join(map(_number_text, row))))
    if not differences:
        return AGREE, []
    return DISAGREE, differences[:MAX_DIFFERENCES]


@dataclass(frozen=True)
class PageReading:
    """The image reading of one page and how it compares with the page's OCR text."""

    page: int
    agreement: str
    image: str
    differences: Tuple[Tuple[str, str], ...] = ()

    @property
    def differs(self) -> bool:
        """Whether the model should read the image reading with the passage, and the reader be warned."""
        return self.agreement in (DISAGREE, IMAGE_ONLY)

    @property
    def excerpt(self) -> str:
        """What the model reads with the passage: the whole reading when OCR found no text, else excerpt()."""
        if self.agreement == IMAGE_ONLY:
            return _cut(self.image, PASSAGE_READING_CHARS)
        return excerpt(self.image, self.differences)

    def as_dict(self, chars: int = SOURCE_READING_CHARS) -> Dict[str, Any]:
        return {"page": self.page, "agreement": self.agreement, "image": _cut(self.image, chars),
                "differences": [list(d) for d in self.differences]}


def _cut(text: str, chars: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= chars else text[:chars].rsplit(" ", 1)[0] + " …"


def _line_matches(differences: Sequence[Tuple[str, str]]) -> List[Tuple[set, bool]]:
    """For each difference, the values a line of the image reading must hold: (values, all of them).

    A changed value (0.5 in vs 1.5 in) is found by the values only the image side
    has. A table row read in another order has the same values on both sides, so
    its line is the one holding all of them. A difference whose values are all
    in the text already (a stretch only the text has, or a value only it has)
    has nothing to show from the image reading.
    """
    out = []
    for ocr, image in differences:
        if image == MISSING:
            continue
        shown = _numbers_of(image)
        theirs = set() if ocr == MISSING else _numbers_of(ocr)
        if shown - theirs:
            out.append((shown - theirs, False))
        elif shown == theirs and len(shown) >= ROW_NUMBERS:
            out.append((shown, True))
    return out


@lru_cache(maxsize=2048)
def excerpt(image: str, differences: Tuple[Tuple[str, str], ...]) -> str:
    """The lines of a page's image reading that hold a value the OCR text reads differently.

    Each such line comes with EXCERPT_CONTEXT_LINES lines either side, and a
    table row with its table's header row, so the model still sees which column
    a value is in (tmsd-h019's 300' is the Desirable Deceleration Length). Gaps
    are marked EXCERPT_GAP. Empty when no line qualifies, as when every
    difference is a stretch only the text has: the image reading then adds no
    value to the passage, and only the notice and the Sources panel show it.
    """
    units = _units(image)
    wanted = _line_matches(differences)
    if not units or not wanted:
        return ""
    keep = set()
    for i, (_, text) in enumerate(units):
        values = _numbers_of(text)
        if not any((need <= values) if every else (need & values) for need, every in wanted):
            continue
        keep.update(range(max(0, i - EXCERPT_CONTEXT_LINES), min(len(units), i + EXCERPT_CONTEXT_LINES + 1)))
        if text.lstrip().startswith("|"):
            top = i
            while top > 0 and units[top - 1][1].lstrip().startswith("|"):
                top -= 1
            keep.update(range(top, min(top + 2, i)))  # the header row and its |---| rule
    if not keep:
        return ""
    # The page's title: on a sideways page the OCR text has none the model can read, and without
    # it the model said the "Recommended Treatment for Turn Lanes" exhibit wasn't there (tmsd-h019).
    keep.update(range(min(EXCERPT_TITLE_LINES, len(units))))
    out, last = "", None
    for i in sorted(keep):
        line, text = units[i]
        if last is None:
            out = text
        elif i > last + 1:
            out += f"\n{EXCERPT_GAP}\n{text}"
        else:
            out += (" " if line == units[last][0] else "\n") + text
        last = i
    return _cut(out, EXCERPT_CHARS)


# A line longer than this is split into sentences for excerpt(): a scanned permit's paragraph
# runs to 900 characters, and utilities-h056's 1 1/2 in is in one sentence of it.
SENTENCE_SPLIT_CHARS = 250
_SENTENCE_END = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")


def _units(image: str) -> List[Tuple[int, str]]:
    """The image reading's non-empty lines, long ones split into sentences, each with its line number."""
    units = []
    for n, line in enumerate(line.rstrip() for line in (image or "").splitlines()):
        if not line.strip():
            continue
        parts = _SENTENCE_END.split(line) if len(line) > SENTENCE_SPLIT_CHARS else [line]
        units += [(n, part) for part in parts if part.strip()]
    return units


@dataclass
class Readings:
    """The index's page readings, by (division, document file, PDF page)."""

    pages: Dict[Tuple[str, str, int], PageReading] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.pages)

    def get(self, division: str, source: str, page: int) -> Optional[PageReading]:
        return self.pages.get((division, source, int(page)))

    def for_part(self, part: Mapping[str, Any]) -> List[PageReading]:
        """The differing readings of the pages a chunk (or one part of a merged passage) covers."""
        division, source, page = part.get("division"), part.get("source"), part.get("page")
        if not (division and source and page):
            return []
        found = []
        for p in range(int(page), int(part.get("page_end") or page) + 1):
            reading = self.get(division, source, p)
            if reading is not None and reading.differs:
                found.append(reading)
        return found

    def annotate(self, hits: Sequence[Hit]) -> List[Hit]:
        """The hits, with `readings` on each chunk part from a page whose two readings differ.

        Copies: the index's chunks are shared by every request. A hit with no such
        page is returned as it is, so pages that agree change nothing downstream.
        """
        if not self.pages:
            return list(hits)
        out = []
        for hit in hits:
            parts = hit.chunk.get("parts")
            if parts:
                new_parts = [_with_readings(p, self.for_part(p)) for p in parts]
                changed = any(n is not p for n, p in zip(new_parts, parts))
                out.append(Hit(hit.score, dict(hit.chunk, parts=new_parts)) if changed else hit)
            else:
                chunk = _with_readings(hit.chunk, self.for_part(hit.chunk))
                out.append(hit if chunk is hit.chunk else Hit(hit.score, chunk))
        return out


def _with_readings(part: Mapping[str, Any], readings: List[PageReading]) -> Any:
    if not readings:
        return part
    return dict(part, readings=[dict(r.as_dict(), excerpt=r.excerpt) for r in readings])


def load(index_dir: Path) -> Readings:
    """page_readings.json beside the index; empty when it is missing or unreadable (answers then go on as before)."""
    path = Path(index_dir) / READINGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Readings()
    except (OSError, ValueError):
        log.warning("%s is unreadable; answering without page readings", path)
        return Readings()
    return from_json(data)


def from_json(data: Mapping[str, Any]) -> Readings:
    """Readings from page_readings.json's shape: {"pages": {division: {file: {page: {...}}}}}."""
    pages: Dict[Tuple[str, str, int], PageReading] = {}
    try:
        for division, files in (data.get("pages") or {}).items():
            for file, by_page in files.items():
                for page, row in by_page.items():
                    if row.get("agreement") not in FLAGS or not isinstance(row.get("image"), str):
                        continue  # not read yet, or the call failed: the page keeps its OCR text alone
                    pages[(division, file, int(page))] = PageReading(
                        int(page), row["agreement"], row["image"],
                        tuple((str(a), str(b)) for a, b in row.get("differences") or ()))
    except (AttributeError, TypeError, ValueError):
        log.warning("page readings are malformed; answering without them")
        return Readings()
    return Readings(pages)


def passage_readings(chunk: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The readings a passage carries (Readings.annotate), one per page, in page order."""
    seen: Dict[int, Dict[str, Any]] = {}
    for part in chunk.get("parts") or [chunk]:
        for reading in part.get("readings") or ():
            seen.setdefault(int(reading["page"]), reading)
    for reading in chunk.get("readings") or ():
        seen.setdefault(int(reading["page"]), reading)
    return [seen[p] for p in sorted(seen)]


def prompt_readings(chunk: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """The passage's readings the model reads: those with an excerpt (passage_readings has them all)."""
    return [r for r in passage_readings(chunk) if r.get("excerpt")]


def reading_text(reading: Mapping[str, Any]) -> str:
    """An image reading as the model reads it after its passage: its excerpt."""
    return READING_HEADER.format(page=reading["page"]) + "\n" + reading["excerpt"]


def _numbers_of(text: str) -> set:
    return {value for value, _ in _numbers(_tokens(text))}


def notice(where: str, readings: Sequence[Mapping[str, Any]], answer: str = "") -> Optional[str]:
    """The warning for one cited source whose page readings differ, or None when none do.

    Only a difference that holds a number the answer states warns the reader: on
    the full run (Nov 24) half of the 1,192 pages differed somewhere, mostly in a
    printed page number, a chart's axis labels or a line one reading left out,
    and a warning about a value the answer doesn't use tells the reader nothing.
    The DAR-732 misreads all qualify: the answer states 1 1/2 in, 2 1/2 or 575 ft,
    and that number is in the difference.
    """
    differing = [r for r in readings if r.get("agreement") in (DISAGREE, IMAGE_ONLY)]
    if not differing:
        return None
    pairs = [tuple(d) for r in differing for d in r.get("differences") or ()]
    if not pairs:
        return NOTICE_NO_TEXT.format(where=where)
    stated = _numbers_of(_CITATION.sub(" ", answer))
    pairs = [d for d in pairs if _numbers_of(d[0] + " " + d[1]) & stated]
    if not pairs:
        return None
    # A value one reading changed (1/2 vs 1 1/2, a row read backwards) says more than a stretch
    # only one reading has, which on a sideways table can be the whole page (tmsd-h019).
    pairs.sort(key=lambda d: MISSING in d)
    shown = "; ".join(_pair_text(_around(ocr, stated), _around(image, stated))
                      for ocr, image in pairs[:NOTICE_DIFFERENCES])
    return NOTICE.format(where=where, pairs=shown)


def _around(snippet: str, stated: set, words: int = NOTICE_WORDS) -> str:
    """A long snippet cut to `words` words either side of the first number the answer states."""
    parts = snippet.split()
    if len(parts) <= 2 * words + 1:
        return snippet
    at = next((i for i, part in enumerate(parts) if _numbers_of(part) & stated), 0)
    start, end = max(0, at - words), min(len(parts), at + words + 1)
    return ("… " if start else "") + " ".join(parts[start:end]) + (" …" if end < len(parts) else "")


# The answer's citation markers ("[1]", "[1, 2]", "[1-3]"): their numbers are not values.
_CITATION = re.compile(r"\[\s*\d+(?:\s*[,\-–]\s*\d+)*\s*\]")


def _pair_text(ocr: str, image: str) -> str:
    if ocr == MISSING:
        return f"“{image}” in the image, not in the text"
    if image == MISSING:
        return f"“{ocr}” in the text, not in the image"
    return f"“{ocr}” in the text vs “{image}” in the image"
