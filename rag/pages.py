"""Which page number a PDF page *prints*, next to its index in the file (DAR-654).

The citation link opens the PDF at `#page=N`, where N is the 1-based index of
the page in the file, and the index keeps that number. But a reader who opens
the TMP Design Manual at PDF page 37 sees "Part 2: Chapter 5 | July 2019 |
Page 13" in the footer, and the Utilities Accommodation Manual numbers its
pages "2-6", "3-27", "D-1": the number printed on the page is what people
quote, so each chunk also learns it. Three sources, in order of trust:

1. the PDF's own page label (`page.get_label()`), the number a viewer shows:
   11 of the 60 documents have labels, and 840 of their 988 pages differ from
   the index (MUTCD Part 6 starts at "765", front matter is "i", "ii"...);
2. a number in the page's footer, then
3. one in its header,

found by regex families (`Page 13`, `5-13`, `A-3`, `iv`, a bare `383`) on the
text lines whose box lies in the top or bottom 12% of the page as displayed
(rotated drawings included). A regex alone also hits sign codes ("W1-1"),
publication numbers ("FHWA-HRT-04-091", "1-24" in a drawing's title block) and
line numbers in the Standard Specifications' footers, so a family only counts
for a document when its hits run through the document like page numbers do:
`consistent` asks that, over the pages where the family hit, at least 70% of
the steps between one hit and the next advance by exactly the distance between
the pages (or restart at 1 where a chapter-numbered manual starts a new
chapter). A sign code is the same on every sheet, a publication number appears
once, and the footer line numbers jump about, so they all fail that test.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

# The slice of the page, top and bottom, where running headers and footers sit.
# The TMP manual's footer line starts at 91% of the page height, the UAM's at
# 94%, the STEP guide's header ends at 7%.
BAND = 0.12
# The share of steps between hits that must advance like page numbers.
MIN_CONSISTENT = 0.7
# A regex family needs hits on this many pages before its steps are believed:
# two sheet numbers 17 pages apart in the Roadway Standard Drawings ("1" on
# p.4, "18" on p.21) happened to advance by the page distance.
MIN_HITS = 3
# Bare integers and roman numerals may never run backwards more often than this
# (a few misreads are tolerated): the sheet numbers in the Roadway Standard
# Drawings' title blocks (1, 2, 3, 1, 2, 3...) restart every standard and would
# otherwise pass as pages 1-3 of a 59-page file.
MAX_DECREASES = 0.1

Source = str  # "label" | "footer" | "header"


@dataclass(frozen=True)
class PageIdentity:
    pdf_index: int  # 1-based position in the file, what `#page=N` opens
    pdf_label: Optional[str]  # the PDF's own page label, decoded, or None
    printed: Optional[str]  # the number printed on the page ("13", "5-13", "A-3", "iv"), or None
    source: Optional[Source]  # where `printed` came from


Hit = Tuple[int, str, str]  # (line counted from the page's edge inwards, family, the number matched)


@dataclass(frozen=True)
class PageCandidates:
    """What one page offers before the document-level consistency pass: its label and every regex hit."""

    label: Optional[str]
    footer: List[Hit]
    header: List[Hit]


# Regex families, in order of preference; each captures the number as printed.
# "Page 13", "Page 2 of 706"; "5-13", "2-48" at a line's start or end (a date like
# "2-9-10" or a code like "FHWA-HOP-13-012" has no whitespace boundary there);
# "A-3", "D-1" the same way; a roman numeral or a bare integer. The integer may
# share its line with the running title ("Federal Highway Administration 224",
# "383 Federal Highway Administration, DOT") but then only at the line's edge.
FAMILIES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("page", re.compile(r"\bPage\s+(\d{1,5})(?:\s+of\s+\d+)?\b", re.IGNORECASE)),
    ("chapter", re.compile(r"(?:^|(?<=\s))(\d{1,2}-\d{1,3})(?=\s|$)")),
    ("appendix", re.compile(r"(?:^|(?<=\s))([A-Z]-\d{1,3})(?=\s|$)")),
    ("roman", re.compile(r"^([ivxlc]+)$")),
    ("integer", re.compile(r"^(\d{1,4})$|^(\d{1,4})(?=\s)|(?<=\s)(\d{1,4})$")),
)
# Families whose numbers legitimately restart at 1 (a new chapter or appendix).
RESTARTING = frozenset({"page", "chapter", "appendix", "label"})
# Families checked as one run: the UAM's footers go "2-48", "3-1" ... "3-27", then
# "D-1", "D-2" in its appendices, on the same footer line. Checked apart, a short
# appendix (two pages) would never reach MIN_HITS on its own.
RUN = {"appendix": "chapter"}

_UTF16_HEX = re.compile(r"^<((?:[0-9A-Fa-f]{4})+)>(.*)$")
_ROMAN = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
_PREFIXED = re.compile(r"^([A-Za-z]{1,3}|\d{1,2})[-–.]?\s*(\d{1,4})$")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

_cache: Dict[Tuple[str, int, int], List[PageIdentity]] = {}


def decode_label(raw: Optional[str]) -> Optional[str]:
    """A page label as a viewer shows it: "" is None, and a UTF-16 hex string is decoded.

    PyMuPDF returns a label whose prefix was stored as a UTF-16 string
    undecoded, "<FEFF0041>1" for "A1" (the STEP guide's cover pages).
    """
    if raw is None:
        return None
    text = raw.strip()
    match = _UTF16_HEX.match(text)
    if match:
        try:
            prefix = bytes.fromhex(match.group(1)).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            prefix = ""
        text = (prefix.lstrip("﻿") + match.group(2)).strip()
    return text or None


def roman_value(text: str) -> Optional[int]:
    """The value of a roman numeral, or None when it isn't one ("Ill" from OCR, "")."""
    # One case only: OCR reads a stray "Ill" for "III" or "11", which isn't a page number.
    if not _ROMAN.match(text) or not (text.islower() or text.isupper()):
        return None
    total, previous = 0, 0
    for char in reversed(text.lower()):
        value = _ROMAN_VALUES[char]
        total += -value if value < previous else value
        previous = max(previous, value)
    # Only a numeral written the standard way: a footer word like "civil" or OCR's
    # "iiii" would otherwise get a value (143, 4) and pass for a page number.
    return total if 0 < total < 4000 and _to_roman(total) == text.lower() else None


def _to_roman(value: int) -> str:
    out = ""
    for number, numeral in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
                            (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        count, value = divmod(value, number)
        out += numeral * count
    return out


def parse_number(text: str) -> Optional[Tuple[str, int]]:
    """(prefix, number) of a printed page number, so two can be compared; None when it has no number.

    "13" -> ("", 13), "5-13" -> ("5", 13), "A-3" -> ("A", 3), "iv" -> ("roman", 4),
    "B" -> ("letter", 2). A single capital is a letter, not a roman numeral:
    the Best Practices Guidebook labels its cover pages "A", "B", "C".
    """
    text = text.strip()
    if text.isdigit():
        return "", int(text)
    # ...except I, V and X, which in front matter labelled I, II, III, IV, V are numerals.
    if len(text) == 1 and "A" <= text <= "Z" and text not in "IVX":
        return "letter", ord(text) - ord("A") + 1
    roman = roman_value(text)
    if roman is not None:
        return "roman", roman
    match = _PREFIXED.match(text)
    if match:
        return match.group(1), int(match.group(2))
    return None


def consistent(found: Dict[int, str], restart: bool, min_hits: int = MIN_HITS) -> bool:
    """Whether the numbers found on these pages run like page numbers.

    `found` maps a page's 1-based index to the number found on it. Each step from
    one hit to the next counts as consistent when the number advances by the
    distance between the two pages (same prefix), or, with `restart`, when it goes
    back to 1 (the TMP manual's "Page 1" at each chapter, the UAM's "3-1" after
    "2-48"). Hits on fewer than `min_hits` pages never count: "Page 1" on a
    report's documentation page is seen once.
    """
    pages = sorted(found)
    if len(pages) < max(2, min_hits):
        return False
    steps = decreases = 0
    for before, after in zip(pages, pages[1:]):
        step = _step(found, before, after, restart)
        if step is True:
            steps += 1
        elif step == "decrease":
            decreases += 1
    pairs = len(pages) - 1
    return steps >= MIN_CONSISTENT * pairs and (restart or decreases <= MAX_DECREASES * pairs)


def _step(found: Dict[int, str], before: int, after: int, restart: bool) -> Union[bool, str]:
    """True when the number on page `after` follows the one on page `before` as a page number would;
    "decrease" when it runs backwards under the same prefix; else False."""
    first, second = parse_number(found[before]), parse_number(found[after])
    if first is None or second is None:
        return False
    (prefix_a, a), (prefix_b, b) = first, second
    if prefix_a == prefix_b and b - a == after - before:
        return True
    if restart and b == 1 and (prefix_a != prefix_b or a > 1):
        return True
    return "decrease" if prefix_a == prefix_b and b < a else False


def in_run(found: Dict[int, str], restart: bool) -> frozenset:
    """The pages whose number steps in sequence with the hit before or after it (the rule in `consistent`)."""
    pages = sorted(found)
    good = set()
    for before, after in zip(pages, pages[1:]):
        # Within a run already accepted, "Page 1" then "Page 1" is a one-page chapter
        # (TMP Part 3, Chapter 2 on PDF p.116), though it can't count towards `consistent`.
        one_page_chapter = restart and parse_number(found[before]) == parse_number(found[after]) == ("", 1)
        if one_page_chapter or _step(found, before, after, restart) is True:
            good.update((before, after))
    return frozenset(good)


def _lines_in_bands(page) -> Tuple[List[str], List[str]]:
    """The text lines in the page's top band and bottom band, as displayed, nearest the edge first.

    Nearest the edge first because a contents page lists "2.8.2 Temporary
    Shoring ..... 2-48" right above its own footer "ii" (UAM p.3), and the page
    number is the line at the very edge.
    """
    import pymupdf

    rect, matrix = page.rect, page.rotation_matrix  # the page as displayed; text boxes are unrotated
    top, bottom = rect.y0 + BAND * rect.height, rect.y1 - BAND * rect.height
    header: List[Tuple[float, str]] = []
    footer: List[Tuple[float, str]] = []
    # Clipped to the page box, so printer marks and cropped title blocks stay out of the bands.
    flags = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_MEDIABOX_CLIP
    text = page.get_text("dict", flags=flags)
    for block in text["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            words = " ".join("".join(span["text"] for span in line["spans"]).split())
            if not words:
                continue
            box = (pymupdf.Rect(line["bbox"]) * matrix).normalize()
            if box.y1 <= top:
                header.append((box.y0 - rect.y0, words))
            elif box.y0 >= bottom:
                footer.append((rect.y1 - box.y1, words))
    return [words for _, words in sorted(header)], [words for _, words in sorted(footer)]


def _candidates(lines: List[str]) -> List[Hit]:
    """Every family's match on every line (the last on a line), nearest the edge first.

    All lines, not just the nearest, because the CFR's "VerDate ... Aug 14, 2024"
    imprint sits under its page number "383": the (line, family) pair is the key
    the consistency pass works on, so each line of a running footer is checked
    on its own.
    """
    hits: List[Hit] = []
    for position, line in enumerate(lines):
        for family, pattern in FAMILIES:
            # The last match: a page number sits at the line's end ("Section 2-4 Utility Relocation | 2-48").
            match = None
            for match in pattern.finditer(line):
                pass
            if match:
                hits.append((position, family, next(g for g in match.groups() if g)))
    return hits


def page_candidates(page) -> PageCandidates:
    """The page's label and the numbers each regex family finds in its header and footer."""
    try:
        label = decode_label(page.get_label())
    except Exception:  # noqa: BLE001 - a malformed label tree; the page then has no label
        label = None
    header, footer = _lines_in_bands(page)
    return PageCandidates(label, _candidates(footer), _candidates(header))


def identities(doc) -> List[PageIdentity]:
    """One PageIdentity per page of an open pymupdf Document, after the consistency pass."""
    candidates = [page_candidates(page) for page in doc]
    labels = {i + 1: c.label for i, c in enumerate(candidates) if c.label}
    # Labels are the producer's own numbering, so two pages ("1", "2" on the positive
    # protection memo) are enough, and a one-page memo's label stands unchecked.
    labels_ok = bool(labels) and (len(doc) == 1 or consistent(labels, restart=True, min_hits=2))
    # A producer's default labels "1", "2", ... repeat the index and say nothing about what
    # the page prints (fhwahop09021, 140 pages): the footer is read first, the label kept as
    # the fallback.
    labels_first = labels_ok and any(label != str(index) for index, label in labels.items())
    order = [family for family, _ in FAMILIES]
    # The numbers each (region, line, family) key found, by page, then which keys run like page numbers.
    found: Dict[Tuple[str, int, str], Dict[int, str]] = {}
    for i, c in enumerate(candidates):
        for region in ("footer", "header"):
            for line, family, number in getattr(c, region):
                found.setdefault((region, line, RUN.get(family, family)), {}).setdefault(i + 1, number)
    # A key that runs like page numbers, and on it only the pages whose number steps in
    # sequence with a neighbouring hit: the TMP manual's footer line passes as a whole, but on
    # a figure page with no footer the line nearest the edge may be body text ending in "45".
    accepted = {key: in_run(numbers, restart=key[2] in RESTARTING)
                for key, numbers in found.items() if consistent(numbers, restart=key[2] in RESTARTING)}
    result: List[PageIdentity] = []
    for i, c in enumerate(candidates):
        printed: Optional[str] = None
        source: Optional[Source] = None
        if labels_first and c.label:
            printed, source = c.label, "label"
        else:
            for region in ("footer", "header"):
                # The accepted hit nearest the page's edge, then the preferred family on that line.
                hits = [(line, order.index(family), number) for line, family, number in getattr(c, region)
                        if i + 1 in accepted.get((region, line, RUN.get(family, family)), ())]
                if hits:
                    printed, source = min(hits)[2], region
                    break
            if printed is None and labels_ok and c.label:
                printed, source = c.label, "label"
        result.append(PageIdentity(i + 1, c.label, printed, source))
    return result


def document_identities(path: Union[str, Path]) -> List[PageIdentity]:
    """The identities of every page of the PDF at `path`, computed once per path."""
    import pymupdf

    resolved = Path(path).resolve()
    stat = resolved.stat()
    key = (str(resolved), stat.st_mtime_ns, stat.st_size)  # a PDF re-fetched to the same path is read again
    if key not in _cache:
        with pymupdf.open(str(resolved)) as doc:
            _cache[key] = identities(doc)
    return _cache[key]


def page_identity(doc, index0: int) -> PageIdentity:
    """The identity of page `index0` (0-based) of `doc`, an open pymupdf Document or a path.

    A document opened from a file is computed once and cached by path; an
    in-memory one (tests) is computed on each call.
    """
    if isinstance(doc, (str, Path)):
        return document_identities(doc)[index0]
    if getattr(doc, "name", ""):
        return document_identities(doc.name)[index0]
    return identities(doc)[index0]


def clear_cache() -> None:
    _cache.clear()
