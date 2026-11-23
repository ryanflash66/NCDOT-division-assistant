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
it where the two differ (it was right on the DAR-733 pages). The image reading
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
# Words either side of a differing number in an "X vs Y" snippet.
SNIPPET_WORDS = 3
# A table row: a line of the image reading with at least this many numbers.
ROW_NUMBERS = 3
# The image reading the model reads with a passage. A page's whole reading averages about
# 1,700 characters (the OCR text of the 1,189 flagged pages: mean 1,656, median 1,427), and
# a few dense drawings run to 20,000; past this the reading is cut with a mark.
PASSAGE_READING_CHARS = 6000
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
            out.append((_snippet(ocr, i1, i2) if i2 > i1 else "(missing)",
                        _snippet(image, j1, j2) if j2 > j1 else "(missing)"))
            wanted -= numbers
        if not wanted:
            break
    for value, unit in sorted(wanted, key=lambda n: (n[0], n[1] or "")):
        # A number the alignment didn't reach: name it alone.
        shown = _number_text(value) + (f" {unit}" if unit else "")
        out.append(("(missing)", shown))
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

    def as_dict(self, chars: int = SOURCE_READING_CHARS) -> Dict[str, Any]:
        return {"page": self.page, "agreement": self.agreement, "image": _cut(self.image, chars),
                "differences": [list(d) for d in self.differences]}


def _cut(text: str, chars: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= chars else text[:chars].rsplit(" ", 1)[0] + " …"


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
    return dict(part, readings=[r.as_dict(PASSAGE_READING_CHARS) for r in readings])


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


def reading_text(reading: Mapping[str, Any]) -> str:
    """An image reading as the model reads it after its passage."""
    return READING_HEADER.format(page=reading["page"]) + "\n" + reading["image"]


def _numbers_of(text: str) -> set:
    return {value for value, _ in _numbers(_tokens(text))}


def notice(where: str, readings: Sequence[Mapping[str, Any]], answer: str = "") -> Optional[str]:
    """The warning for one cited source whose page readings differ, or None when none do.

    The differences that hold a number the answer states come first, so the
    notice names the value the reader is about to rely on.
    """
    differing = [r for r in readings if r.get("agreement") in (DISAGREE, IMAGE_ONLY)]
    if not differing:
        return None
    pairs = [tuple(d) for r in differing for d in r.get("differences") or ()]
    if not pairs:
        return NOTICE_NO_TEXT.format(where=where)
    stated = _numbers_of(answer)
    pairs.sort(key=lambda d: not (_numbers_of(d[0] + " " + d[1]) & stated))
    shown = "; ".join(f"“{ocr}” in the text vs “{image}” in the image"
                      for ocr, image in pairs[:NOTICE_DIFFERENCES])
    return NOTICE.format(where=where, pairs=shown)
