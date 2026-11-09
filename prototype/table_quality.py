"""Quality flags for the Markdown tables in a chunk, computed at index time (DAR-655).

A table that pymupdf4llm read badly still embeds and reranks like any other
chunk, so the first sign of trouble was a wrong answer: the TMP Design Manual's
deflection table (p. 37) has its rotated row header "Offset (ft)" broken into
"ft)", "et (", "ffs", "O" down the first column and its column header
"Design Speed (mph)" spread over five cells ("D", "esign Sp", "eed(mph", ")").
These checks mark such chunks with `flags` in chunks.json, so a build report
(prototype.build_report) can count them per document and a later unit can route
the flagged pages to a better extractor.

Flags (the values are a shared contract with the other DAR-652 units):

    empty_header        a header cell with no text (outside the row-label column)
    column_mismatch     a row with a different cell count from the header
    low_text            rows that carry almost no letters or digits
    fragmented_header   header or row-label text split into fragments
    no_caption          no "Figure N"/"Table N" line in the chunk and no context line
    rotated             most of the page's text is set at an angle (needs the PDF)
    ocr_low_conf        set by the OCR unit; carried, never computed here

Everything here is a pure function of the chunk text (plus optional page info),
so it is unit-testable without PDFs; `pdf_page_stats` is the one reader.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rag.tables import _header_row_count, cells, is_separator, is_table_line

FLAGS = ("empty_header", "column_mismatch", "low_text", "rotated", "no_caption", "fragmented_header", "ocr_low_conf")

# A figure or table caption line, as prototype.ingest.captions finds them
# ("Figure 5 – NC-PCB impact design table...", "TABLE 3 (continued)"); kept
# separate from ingest so this module needs neither the embedder nor the loader.
_CAPTION = re.compile(r"^[#*\s]*(?:<u>)?\s*(?:Figure|FIGURE|Table|TABLE|Exhibit)\s+[0-9A-Z][\w.\-]*\b", re.MULTILINE)
_MARKUP = re.compile(r"\*\*|__|</?(?:u|b|i|em|strong|mark)>")
_ALNUM = re.compile(r"[0-9A-Za-z]")
_LETTERS = re.compile(r"[A-Za-z]+")
# An enumerated row label ("1)", "a)", "(iv)"): its lone bracket is not a split word.
_ENUMERATION = re.compile(r"^\(?[0-9A-Za-z]{1,4}\)$")
# low_text: a table whose rows average fewer letters and digits than this is a
# grid read from a drawing or a form (the WZTC standard drawings' title blocks
# come out as rows of "| | | |"), not a table a question can be answered from.
# Five is below any real row: even "|8|11.1|" has five. A narrower table needs
# only one per column, so a 3-column table of single digits ("|2|3|1|") passes.
MIN_ALNUM_PER_ROW = 5
# ...or whose text is mostly pipes, dashes and bold marks: the separator row
# alone is 4 characters per column, so an empty 8-column table is 97% markup.
MIN_ALNUM_SHARE = 0.15
# fragmented_header: share of short letter-only tokens (after stripping
# punctuation) among the header's letter-only tokens. Real headers have few
# ("of", "in") and those are whitelisted below; a header split per glyph by a
# rotated text run ("D", "Sp", "et", "O" on TMP p. 37) has many. 0.4 leaves
# room for one or two genuine abbreviations in a short header.
FRAGMENT_SHARE = 0.4
# Short words and units that are not fragments: "Width (ft)", "Speed in mph",
# "Vol. of traffic", "No." of lanes.
_SHORT_WORDS = frozenset("""
a an as at by cu do ea ft g h hp hr id if in is kg km lb lf ls m mi mm mo no of on or oz
s sf sq sy to ts up vs yd yr ac dc av rt lt n e w ne nw se sw mt
""".split())
# rotated: share of the page's characters on lines whose direction is not
# horizontal (pymupdf line["dir"]). Landscape tables printed on portrait pages
# (the TMP manual's deflection tables) are around 0.9; a page whose only
# rotated text is a figure's axis label is under 0.05.
ROTATED_SHARE = 0.3


def _tables(text: str) -> List[Tuple[List[str], List[str]]]:
    """Each Markdown pipe table in `text` as (lines above it, table rows).

    A run of `|` lines counts as a table only with a separator row, so a prose
    line that happens to start with "|" (a quoted spec) is not one.
    """
    lines = text.split("\n")
    tables: List[Tuple[List[str], List[str]]] = []
    i = 0
    while i < len(lines):
        if not is_table_line(lines[i]):
            i += 1
            continue
        j = i
        while j < len(lines) and is_table_line(lines[j]):
            j += 1
        rows = lines[i:j]
        if any(is_separator(r) for r in rows):
            tables.append((lines[:i], rows))
        i = j
    return tables


def has_table(text: str) -> bool:
    """Whether the chunk holds a Markdown table (the `kind` field, when a build sets it, says so directly)."""
    return bool(_tables(text))


def _clean(cell: str) -> str:
    return _MARKUP.sub("", cell).strip()


def _header_rows(rows: List[str]) -> List[List[str]]:
    """The header rows' cells (without the separator), as the splitter repeats them in every piece."""
    return [cells(r) for r in rows[:_header_row_count(rows)] if not is_separator(r)]


def _data_rows(rows: List[str]) -> List[List[str]]:
    return [cells(r) for r in rows[_header_row_count(rows):] if not is_separator(r)]


def empty_header(rows: List[str]) -> bool:
    """A header cell outside the first column is blank.

    The first column's header is left blank on purpose in design tables (the
    corner above the row labels, "||UNDER 750|7 - 10|"), so only the other
    columns count: a blank one there is a column the model cannot name when it
    cites a value (TMP p. 37: "|**Imp**|**act Angle (degree)/**||**D**|...").
    """
    return any(not _clean(c) for header in _header_rows(rows) for c in header[1:])


def column_mismatch(rows: List[str]) -> bool:
    """Some row has a different number of cells from the first header row."""
    width = len(cells(rows[0]))
    return any(len(cells(r)) != width for r in rows[1:])


def low_text(rows: List[str]) -> bool:
    """The table's rows carry almost no letters or digits (see MIN_ALNUM_PER_ROW, MIN_ALNUM_SHARE)."""
    data = _data_rows(rows) or _header_rows(rows)
    per_row = [sum(len(_ALNUM.findall(_clean(c))) for c in row) for row in data]
    block = "\n".join(rows)
    share = len(_ALNUM.findall(block)) / max(len(block), 1)
    minimum = min(MIN_ALNUM_PER_ROW, len(cells(rows[0])))
    return (bool(per_row) and sum(per_row) / len(per_row) < minimum) or share < MIN_ALNUM_SHARE


def _unbalanced(cell: str) -> bool:
    return cell.count("(") != cell.count(")") or cell.count("[") != cell.count("]")


def fragmented_header(rows: List[str]) -> bool:
    """Header text, or the row-label column, is broken into fragments.

    Two signs, either is enough. A cell with an opening bracket but no closing
    one (or the reverse): "eed(mph" and ")" in the TMP p. 37 column header,
    "ft)" and "et (" in its row labels, where pymupdf4llm split the rotated
    "Offset (ft)" and "Design Speed (mph)" per glyph run. Or at least
    FRAGMENT_SHARE of the letter-only tokens being one or two letters that are
    not a known short word or unit. The token share alone does not catch
    p. 37 (4 of 17 tokens), which is why the bracket check is there. The token
    share reads the header only: row labels are often single letters on purpose
    (level-of-service rows A to F, state codes NC, SC, VA).
    """
    headers = [_clean(c) for header in _header_rows(rows) for c in header]
    row_labels = [_clean(row[0]) for row in _data_rows(rows) if row]
    if any(_unbalanced(t) and not _ENUMERATION.match(t) for t in headers + row_labels):
        return True
    tokens = [t for text in headers for t in _LETTERS.findall(text)]
    short = [t for t in tokens if len(t) <= 2 and t.lower() not in _SHORT_WORDS]
    return len(tokens) >= 3 and len(short) / len(tokens) >= FRAGMENT_SHARE


def no_caption(text: str, context: Optional[str]) -> bool:
    """Neither the chunk nor its context line names a figure or table.

    The TMP manual prints the caption under each table, and the splitter leaves
    it in a chunk of its own; the `context` line (prototype.ingest.context_line)
    carries it back to every chunk of the page. Without either, the asphalt and
    concrete deflection tables (p. 37, 38) are told apart by nothing but their numbers.
    """
    return not context and not _CAPTION.search(text)


def table_flags(chunk_text: str, page_info: Optional[Dict] = None, context: Optional[str] = None) -> List[str]:
    """The quality flags of a chunk's Markdown tables, in FLAGS order; [] for a chunk without a table.

    `page_info` is the chunk's page from `pdf_page_stats` (its `rotated_share`
    sets `rotated`); `context` is the chunk's caption context line, if any.
    """
    tables = _tables(chunk_text)
    if not tables:
        return []
    found = set()
    for _, rows in tables:
        if empty_header(rows):
            found.add("empty_header")
        if column_mismatch(rows):
            found.add("column_mismatch")
        if low_text(rows):
            found.add("low_text")
        if fragmented_header(rows):
            found.add("fragmented_header")
    if no_caption(chunk_text, context):
        found.add("no_caption")
    if page_info and page_info.get("rotated_share", 0) > ROTATED_SHARE:
        found.add("rotated")
    return [f for f in FLAGS if f in found]


def chunk_flags(chunk: Dict, page_info: Optional[Dict] = None) -> List[str]:
    """`table_flags` of an index chunk, keeping any flags another step set on it (ocr_low_conf)."""
    found = set(table_flags(chunk["text"], page_info, chunk.get("context")))
    carried = [f for f in chunk.get("flags") or [] if f not in found]
    found.update(carried)
    return [f for f in FLAGS if f in found] + [f for f in carried if f not in FLAGS]


def flag_chunks(chunks: Iterable[Dict], pdf: Optional[Path]) -> int:
    """Set `flags` on each chunk of one document (dropping the key when empty); the number flagged.

    `pdf` is the document's file, read for per-page rotation (None, or a
    non-PDF, flags from the text alone).
    """
    chunks = list(chunks)
    # Only the rotation check needs the PDF, and only for a chunk with a table:
    # a document with none (most of the SOPs) is not read a second time.
    wanted = pdf is not None and any(c.get("kind") == "table" or has_table(c["text"]) for c in chunks)
    stats = pdf_page_stats(Path(pdf)) if wanted else {}
    flagged = 0
    for chunk in chunks:
        flags = chunk_flags(chunk, stats.get(chunk.get("page")))
        if flags:
            chunk["flags"] = flags
            flagged += 1
        else:
            chunk.pop("flags", None)
    return flagged


@lru_cache(maxsize=None)
def pdf_page_stats(path: Path) -> Dict[int, Dict]:
    """Per PDF page (1-based): `chars` in the text layer and `rotated_share` of them on non-horizontal lines.

    Cached by path: the ingest reads each document once for its chunks' flags
    and the build report reads it again for its page columns. Non-PDFs give {}.

    line["dir"] is in the unrotated page's space, so on a page stored with
    /Rotate 90 (WZ Safety and Mobility Guidelines p. 7, a landscape page that
    reads normally) every line looks vertical; turning dir by the page's
    rotation matrix measures it as the reader sees it.
    """
    if path.suffix.lower() != ".pdf" or not path.is_file():
        return {}
    import pymupdf  # installed with pymupdf4llm, which the loader reads PDFs with

    stats: Dict[int, Dict] = {}
    with pymupdf.open(path) as pdf:
        for number, page in enumerate(pdf, start=1):
            m = page.rotation_matrix
            turn = pymupdf.Matrix(m.a, m.b, m.c, m.d, 0, 0)  # rotation only, for a direction vector
            total = rotated = 0
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    n = sum(len(span["text"]) for span in line["spans"])
                    total += n
                    # line["dir"] is the unit writing direction; (1, 0) is horizontal.
                    if abs((pymupdf.Point(line["dir"]) * turn).x) < 0.9:
                        rotated += n
            stats[number] = {"chars": total, "rotated_share": rotated / total if total else 0.0}
    return stats


def preview(text: str, width: int = 80) -> str:
    """The first `width` characters of a chunk on one line, for the report."""
    return " ".join(text.split())[:width]
