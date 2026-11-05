"""What the bake-off measures on one page of extractor output (standard library only).

Every candidate's output is Markdown (pymupdf4llm, Docling) or Markdown with
HTML tables (MinerU), and the text layer is plain text, so the measures here
read all three the same way: table blocks are runs of `|` lines or
`<table>...</table>`, rows are table lines or `<tr>` elements, and everything
else is a line of text.
"""

import html
import re
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

_NUMBER = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?|(?<![\w.])\.\d+")
# Unit tokens the manuals use; quote marks count only straight after a number
# (12' and 6"), as they are also ordinary quotes.
_UNIT = re.compile(
    r"(?<![a-z])(ft|feet|foot|in\.|inch(?:es)?|mph|mi/h|lbs?|kips?|psi|sq\.?\s?ft|mm|cm|km|kg|"
    r"percent|deg(?:rees)?|sec(?:onds)?|min(?:utes)?|hours?|days?|years?|miles?)(?![a-z])"
    r"|%|°|(?<=\d)['’′]|(?<=\d)[\"”″]",
    re.I,
)
_UNIT_CANON = {"feet": "ft", "foot": "ft", "'": "ft", "’": "ft", "′": "ft", "in.": "in", "inch": "in",
               "inches": "in", '"': "in", "”": "in", "″": "in", "mi/h": "mph", "lb": "lbs",
               "kip": "kips", "percent": "%", "deg": "°", "degree": "°", "degrees": "°", "sec": "s",
               "second": "s", "seconds": "s", "min": "min", "minute": "min", "minutes": "min",
               "hour": "h", "hours": "h", "day": "day", "days": "day", "year": "yr", "years": "yr",
               "mile": "mi", "miles": "mi"}
CAPTION = re.compile(r"^\W{0,6}((?:Table|TABLE|Figure|FIGURE|Exhibit|EXHIBIT|Chart|CHART)\s+[A-Z]?[\d][\w.\-]*)")
_TAG = re.compile(r"<[^>]+>")
_TABLE_HTML = re.compile(r"<table\b.*?</table>", re.S | re.I)
_ROW_HTML = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
_CELL_HTML = re.compile(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", re.S | re.I)
_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}")
_EMPHASIS = re.compile(r"\*\*|__|`")


_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")


def strip_images(text: str) -> str:
    """Markdown images reduced to their alt text: MinerU inlines every picture as a
    base64 data URI, whose letters and digits would count as hundreds of "numbers"."""
    return _IMAGE.sub(lambda m: m.group(1), text)


def normalize(text: str) -> str:
    """Lower case, HTML entities decoded, tags and Markdown emphasis dropped, whitespace collapsed,
    dashes made '-'."""
    text = _EMPHASIS.sub("", html.unescape(_TAG.sub(" ", text)))
    # part6.pdf prints sign codes with non-breaking hyphens ("W1‑6"); OCR and other tools give "-".
    for dash in "‐‑‒–—−":
        text = text.replace(dash, "-")
    text = text.replace(" ", " ")
    return " ".join(text.lower().split())


def numbers(text: str) -> Counter:
    """Multiset of the numbers on the page, thousands commas dropped ("1,500" == "1500")."""
    # Tags go first: MinerU's colspan="2" / rowspan=3 are not numbers on the page.
    return Counter(m.group(0).replace(",", "") for m in _NUMBER.finditer(html.unescape(_TAG.sub(" ", text))))


def units(text: str) -> Counter:
    out: Counter = Counter()
    for m in _UNIT.finditer(html.unescape(_TAG.sub(" ", text))):
        token = m.group(0).lower()
        token = re.sub(r"\s", "", token)
        out[_UNIT_CANON.get(token, token)] += 1
    return out


def multiset_overlap(reference: Counter, found: Counter) -> int:
    return sum((reference & found).values())


def _pipe_cells(line: str) -> List[str]:
    # One border pipe off each end only: "||maximum deflection|" starts with an empty cell.
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") else line
    return [c.strip() for c in line.split("|")]


def tables(text: str) -> List[Dict]:
    """Each table block: its header cells (first row) and its line span in `lines(text)`."""
    found: List[Dict] = []
    for m in _TABLE_HTML.finditer(text):
        rows = _ROW_HTML.findall(m.group(0))
        header = [normalize(c) for c in _CELL_HTML.findall(rows[0])] if rows else []
        found.append({"header": header, "rows": len(rows), "html": True})
    block: List[str] = []
    for line in text.splitlines() + [""]:
        if line.lstrip().startswith("|"):
            block.append(line)
            continue
        if len(block) >= 2:
            rows = [l for l in block if not _SEPARATOR.match(l.strip())]
            found.append({"header": [normalize(c) for c in _pipe_cells(rows[0])] if rows else [],
                          "rows": len(rows), "html": False})
        block = []
    return found


def rows(text: str) -> List[str]:
    """The page as rows: one per table row (HTML or pipe) and one per other non-empty line."""
    return [row for row, _ in _row_records(text)]


def _row_records(text: str) -> List[Tuple[str, bool]]:
    """(row, continues the row before): a table row under a row-spanned label (HTML row
    with fewer cells than the one above, or a pipe row whose first cell is empty), or a
    text line wrapped from the line above. TMP p.37's "Maximum Deflection" row sits under
    the offset ("14") that spans it and the "Impact Angle" row."""
    out: List[Tuple[str, bool]] = []
    for m in _TABLE_HTML.finditer(text):
        previous = None
        for r in _ROW_HTML.findall(m.group(0)):
            n = len(_CELL_HTML.findall(r))
            out.append((normalize(r), previous is not None and n < previous))
            previous = n
    previous_kind = None
    for line in _TABLE_HTML.sub("\n", text).splitlines():
        stripped = line.strip()
        if not stripped or _SEPARATOR.match(stripped):
            continue
        if stripped.startswith("|"):
            cells = _pipe_cells(stripped)
            out.append((normalize(line), previous_kind == "table" and bool(cells) and not normalize(cells[0])))
            previous_kind = "table"
        else:
            out.append((normalize(line), previous_kind == "text"))
            previous_kind = "text"
    return out


def header_fragmentation(header_cells: Sequence[str]) -> Optional[float]:
    """Share of header words of one or two letters: "Offset (ft)" read glyph by glyph
    comes out as "ft)", "et (", "ffs", "O", which scores high; a clean header scores low."""
    words = [w for cell in header_cells for w in re.findall(r"[a-z]+", cell)]
    if not words:
        return None
    return sum(1 for w in words if len(w) <= 2 and w not in {"ft", "in", "of", "to", "or", "at", "no", "by", "mm"}) / len(words)


def captions(text: str) -> List[str]:
    """Caption labels on the page ("figure 4", "table 6h-1"); the match is on the original case,
    so a sentence that merely starts with "table" is not counted."""
    out = []
    for line in _EMPHASIS.sub("", _TAG.sub(" ", text)).splitlines():
        m = CAPTION.match(line.lstrip("#*_ |"))
        if m:
            out.append(normalize(m.group(1)))
    return out


def caption_attached(text: str, window: int = 3) -> Optional[bool]:
    """True when some table has a caption line within `window` text lines above or below it.

    None when the page has no table. This is the check the near-duplicate
    deflection tables (TMP p.37 Figure 4 / p.38 Figure 5) need: the caption must
    stay next to the numbers, not drift into a chunk of its own.
    """
    lines = [l for l in _TABLE_HTML.sub("\n|<table>|\n", text).splitlines() if l.strip()]
    in_table = [l.lstrip().startswith("|") for l in lines]
    if not any(in_table):
        return None
    for i, flag in enumerate(in_table):
        starts = flag and (i == 0 or not in_table[i - 1])
        ends = flag and (i == len(lines) - 1 or not in_table[i + 1])
        if not (starts or ends):
            continue
        # An HTML table is one line here, so it both starts and ends: look on both sides.
        near = list(range(max(0, i - window), i)) if starts else []
        near += list(range(i + 1, min(len(lines), i + 1 + window))) if ends else []
        if any(CAPTION.match(_EMPHASIS.sub("", lines[j]).lstrip("#*_ ")) for j in near if not in_table[j]):
            return True
    return False


def cell_found(text: str, value: str, row_label: Optional[str] = None, column: Optional[str] = None) -> bool:
    """A hand-checked cell is read right when one row holds the value and its row label.

    With no row label (a header cell such as "Offset (ft)"), the value must appear
    verbatim (after normalize) anywhere on the page. `column` is not required to
    sit in the same row (headers are rows of their own); it must appear on the page.
    """
    value_n = normalize(value)
    if column and normalize(column) not in normalize(text):
        return False
    if row_label is None:
        return value_n in normalize(text)
    label_n = normalize(row_label)
    records = _row_records(text)
    # Label and value may sit on two rows only when the second continues the first
    # (row-spanned label, wrapped line), not when it is the next labelled row.
    windows = [r for r, _ in records] + [a + " " + b for (a, _), (b, cont) in zip(records, records[1:]) if cont]
    return any(_has_token(r, value_n) and _has_token(r, label_n) for r in windows)


def _has_token(row: str, value: str) -> bool:
    """`value` appears in `row` as a whole token: "27.42" is not in "127.42", "14" is not in "12.14"."""
    return re.search(r"(?<![\w.])" + re.escape(value) + r"(?!\w)(?!\.\d)", row) is not None
