"""Markdown tables in Document text: cleanup, and chunking that keeps them whole.

PDF pages arrive as Markdown with tables as pipe tables (see rag/loader.py).
Plain sentence splitting cuts those tables anywhere, so a chunk can hold rows
whose column headers are in another chunk. `split_text` instead cuts prose with
a sentence splitter and cuts tables only between rows, repeating the table's
caption and header rows in every piece.
"""

import re
from typing import Any, Callable, List, Optional, Sequence, Tuple

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.node_parser.interface import TextSplitter
from llama_index.core.utils import get_tokenizer
from pydantic import Field, PrivateAttr

from rag import table_notes, table_rows
from rag.table_rows import cells, is_separator  # noqa: F401  (part of this module's API)

# A data cell: numbers, ranges and placeholders such as "12 - 14", "1.3", "--", "**".
_NUMERIC_CELL = re.compile(r"^[\s\d.,\-–*~<>≥≤%$/\[\]]+$")
# Caption lines kept with a table: short lines just above it (title, units line).
_MAX_CAPTION_LINES = 2
_MAX_CAPTION_CHARS = 200
# Header rows after the separator that are still headers (e.g. Table 3-1's
# "DESIGN SPEED | DESIGN ADT | 1V:6H or flatter ..." rows).
_MAX_EXTRA_HEADER_ROWS = 3
# Prose shorter than this (page headers/footers) is kept with the next table
# instead of becoming a chunk of its own.
_MIN_PROSE_TOKENS = 25
# A table's notes block repeats in every piece of the table, so notes longer than
# this share of a chunk stay prose after it. UAM Table 3-1's three notes are
# about 150 of 512 tokens; a third leaves the rows most of each piece.
_MAX_NOTES_SHARE = 1 / 3


def is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _row(values: List[str]) -> str:
    return "|" + "|".join(values) + "|"


def _merge_spanning_header(rows: List[str]) -> List[str]:
    """Fold a spanning column title into the real header row.

    pymupdf4llm renders a grid such as

        |RADIUS [ft]|||DESI |GN SPEED [ |mph] |||
        |---|---|---|---|---|---|---|---|
        ||40|45|50|55|60|65|70|

    where "DESIGN SPEED [mph]" spans the speed columns and is broken across
    cells. This becomes one header row, "|RADIUS [ft] \\ DESIGN SPEED [mph]|40|...|70|",
    so each value sits under a single, readable column name.
    """
    if len(rows) < 3 or not is_separator(rows[1]):
        return rows
    header, below = cells(rows[0]), cells(rows[2])
    fragments = [cell.strip() for cell in header[1:] if cell.strip()]
    spans = header[0].strip() and fragments and len(fragments) < len(header) - 1
    real_header_below = (
        len(below) == len(header) and not below[0].strip() and all(cell.strip() for cell in below[1:])
    )
    if not (spans and real_header_below):
        return rows
    title = re.sub(r"\s+", " ", "".join(fragments)).strip()
    merged = [f"{header[0].strip()} \\ {title}"] + [cell.strip() for cell in below[1:]]
    return [_row(merged), rows[1]] + rows[3:]


_BRACKETED = re.compile(r"^\s*\[([^\[\]]+)\]\s*$")


def _unwrap_bracketed_units(rows: List[str]) -> List[str]:
    """Drop the brackets around values in columns whose header names a unit in brackets.

    Manuals often print US customary values in brackets next to metric ones:

        |Speed (km/h)|Widths (m)|Speed [mph]|Widths [ft]|
        |90|7|[55]|[23]|

    The brackets are a typographic convention, but they stop models matching
    "55 mph" or "30–40 mph" to "[55]" / "[30 - 40]". Values become "55" and
    "23", while the header keeps saying which unit each column is in.
    """
    if len(rows) < 3 or not is_separator(rows[1]):
        return rows
    header = cells(rows[0])
    unit_columns = {i for i, cell in enumerate(header) if re.search(r"\[[^\]]+\]", cell)}
    if not unit_columns:
        return rows
    out = rows[:2]
    for row in rows[2:]:
        values = cells(row)
        if len(values) != len(header):
            out.append(row)
            continue
        out.append(_row([
            _BRACKETED.sub(r"\1", value) if i in unit_columns else value
            for i, value in enumerate(values)
        ]))
    return out


def _group_label(fragments: List[str]) -> str:
    """Join a row-group label that the PDF split over several rows.

    "40 mph" + "or less" -> "40 mph or less"; "45 - 50" + "mph" -> "45 - 50 mph".
    Rotated text can also come out with its letters split out of order
    ("60 h" + "mp"); when the letters after the number spell "mph" in some
    order, they are written as "mph".
    """
    label = re.sub(r"\s+", " ", " ".join(f.strip() for f in fragments)).strip()
    match = re.fullmatch(r"([\d\s\-–]+?)\s*([a-zA-Z\s]+)", label)
    if match and sorted(match.group(2).replace(" ", "").lower()) == sorted("mph"):
        return f"{match.group(1).strip()} mph"
    return label


def _fill_row_group_labels(rows: List[str]) -> List[str]:
    """Write a grouped row label on every row of its group.

    Tables such as "clear zone by design speed x ADT" print each speed once,
    spread over the rows of its group, leaving the other rows blank:

        ||UNDER 750|7 - 10|...
        |40 mph|750 - 1500|10 - 12|...
        |or less|1500 - 6000|12 - 14|...
        ||OVER 6000|14 - 16|...

    A group is recognised by the second column cycling through the same
    values (UNDER 750 ... OVER 6000) in every group. Each row then gets the
    full label ("40 mph or less"), so a row read on its own, or a chunk that
    starts mid-table, still says which group it belongs to.
    """
    n_header = _header_row_count(rows)
    data = [cells(row) for row in rows[n_header:]]
    if len(data) < 4 or any(len(r) != len(data[0]) or len(r) < 3 for r in data):
        return rows
    cycle_start = data[0][1].strip()
    starts = [i for i, r in enumerate(data) if r[1].strip() == cycle_start]
    if len(starts) < 2 or starts[0] != 0:
        return rows
    bounds = starts + [len(data)]
    groups = [data[a:b] for a, b in zip(bounds, bounds[1:])]
    keys = [[r[1].strip() for r in g] for g in groups]
    if len(groups[0]) < 2 or any(k != keys[0] for k in keys):
        return rows
    labels = [[r[0] for r in g if r[0].strip()] for g in groups]
    if not all(labels) or not any(len(l) < len(g) for l, g in zip(labels, groups)):
        return rows  # every group needs a label, and some rows must be blank
    out = rows[:n_header]
    for group, fragments in zip(groups, labels):
        label = _group_label(fragments)
        out.extend(_row([label] + r[1:]) for r in group)
    return out


def _clean_table(rows: List[str], rotated: Sequence[str]) -> List[str]:
    """One pipe table made readable row by row (DAR-655, see rag/table_rows.py).

    TMP Design Manual p. 37: the rows of offset 14 were stacked into one with
    `<br>`, which broke the group detection, and the rotated row header
    "Offset (ft)" was scattered over column 0 as "ft)", "et (", "ffs", "O", so
    the rows for 14, 20 and 26 had no label and column 0 no header. Stacked
    rows are split and rotated fragments removed while the `<br>` still marks
    where cells were stacked; header spans and row labels are filled last,
    once the older fixes have settled which rows are headers.
    """
    rows = table_rows.unstack_rows(rows)
    rows, rotated_columns = table_rows.strip_rotated_fragments(rows, rotated)
    rows = [line.replace("<br>", " ") for line in rows]
    rows = _fill_row_group_labels(_unwrap_bracketed_units(_merge_spanning_header(rows)))
    n_header = _header_row_count(rows)
    rows = table_rows.fill_header_spans(rows, n_header)
    rows = table_rows.label_column(rows, n_header, rotated_columns)
    return table_rows.fill_row_labels(rows, n_header)


def clean_markdown_tables(text: str, rotated: Sequence[str] = ()) -> str:
    """Tidy every pipe table in `text` (see `_clean_table`); `<br>` elsewhere becomes a space.

    `rotated` is the page's text-layer lines that do not run left to right
    (pymupdf `line["dir"] != (1, 0)`), used to recognise a vertical label
    that the Markdown grid scattered over cells.
    """
    lines = text.split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        if is_table_line(lines[i]):
            j = i
            while j < len(lines) and is_table_line(lines[j]):
                j += 1
            out.extend(_clean_table(lines[i:j], rotated))
            i = j
        else:
            out.append(lines[i].replace("<br>", " "))
            i += 1
    return "\n".join(out)


def _bold(row: str) -> bool:
    """Every non-empty cell of the row is bold (**...**)."""
    values = [cell.strip() for cell in cells(row) if cell.strip()]
    return bool(values) and all(len(v) > 4 and v.startswith("**") and v.endswith("**") for v in values)


def _header_row_count(rows: List[str]) -> int:
    """Rows that label columns: through the separator, plus header-like rows after it.

    Rows after the separator count as headers only when the table has numeric
    data further down, so all-text tables (e.g. state criteria) aren't mistaken
    for having a multi-row header. A bold row right after the separator is a
    header even when it holds numbers, as long as the data rows below are not
    all bold: the TMP manual's deflection tables (p. 37, 38) print the design
    speeds "**30**|**40**|...|**80**" as a bold row under the separator, and
    without it the second piece of a split table had no speeds, so the model
    read 42.89 from the wrong column. A table set entirely in bold (the TODS
    county list) keeps one header row.
    """
    if len(rows) < 2 or not is_separator(rows[1]):
        return 1 if rows else 0

    def numeric(row: str) -> bool:
        return any(cell.strip() and _NUMERIC_CELL.match(cell) for cell in cells(row)[1:])

    has_numeric = any(numeric(row) for row in rows[2:])
    has_plain = any(not _bold(row) for row in rows[2:])
    count = 2
    while count < len(rows) and count - 2 < _MAX_EXTRA_HEADER_ROWS:
        row = rows[count]
        if (has_plain and _bold(row)) or (has_numeric and not numeric(row)):
            count += 1
        else:
            break
    return count


def _segments(text: str) -> List[Tuple[str, str, List[str]]]:
    """Split text into ("prose", text, []) and ("table", caption + table, notes) segments.

    A table's notes are the note lines right under it (rag.table_notes, DAR-717):
    taken before the next table's caption is looked for, so a "Note:" between
    two tables stays with the one above it (FHWA road user cost report p.50,
    Table 24) instead of becoming the caption of the one below.
    """
    lines = text.split("\n")
    segments: List[Tuple[str, str, List[str]]] = []
    prose: List[str] = []
    i = 0
    while i < len(lines):
        if not is_table_line(lines[i]):
            prose.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and is_table_line(lines[j]):
            j += 1
        notes, after_notes = table_notes.trailing_notes(lines, j, "\n".join(lines[i:j]))
        # Pull the caption (short lines right above the table) out of the prose.
        caption: List[str] = []
        while prose and len(caption) < _MAX_CAPTION_LINES:
            if not prose[-1].strip():
                prose.pop()
                continue
            if len(prose[-1]) > _MAX_CAPTION_CHARS or is_table_line(prose[-1]):
                break
            caption.insert(0, prose.pop())
        if "\n".join(prose).strip():
            segments.append(("prose", "\n".join(prose), []))
        segments.append(("table", "\n".join(caption + lines[i:j]), notes))
        prose = []
        i = after_notes if notes else j
    if "\n".join(prose).strip():
        segments.append(("prose", "\n".join(prose), []))
    return segments


# A caption line that names the table, repeated in the "Rows (...)" heading.
_TABLE_CAPTION = re.compile(r"^[#*_\s]*((?:Table|TABLE|Figure|FIGURE|Exhibit)\b.*?)[*_\s]*$")


def _caption_title(caption: List[str]) -> str:
    for line in caption:
        match = _TABLE_CAPTION.match(line)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return ""


def _pack(units: List[List[int]], cost: Callable[[int], int], budget: int) -> List[List[int]]:
    """Consecutive units of row indexes packed into pieces of at most `budget`; a unit too big alone is cut row by row."""
    pieces: List[List[int]] = []
    piece: List[int] = []
    used = 0
    for unit in units:
        size = sum(cost(i) for i in unit)
        if size > budget:
            unit_rows = [[i] for i in unit]
            if piece:
                pieces.append(piece)
                piece, used = [], 0
            pieces.extend(_pack(unit_rows, cost, budget) if len(unit) > 1 else unit_rows)
            continue
        if piece and used + size > budget:
            pieces.append(piece)
            piece, used = [], 0
        piece.extend(unit)
        used += size
    if piece:
        pieces.append(piece)
    return pieces


def _split_table(block: str, chunk_size: int, count: Callable[[str], int], notes: str = "") -> List[str]:
    """The table as one chunk if it fits; otherwise row groups that each repeat caption and header.

    When the table has labelled rows (DAR-655, `table_rows.row_labels`), each
    piece is its grid rows followed by those rows' labelled lines, and a row
    label's rows stay together (TMP p. 37: the Impact Angle and Maximum
    Deflection rows of one offset), so a piece never holds a deflection
    without its offset and design speed.

    `notes` (the table's "Notes:" block, rag.table_notes) ends every piece: a
    note qualifies the whole table (UAM Table 3-1's footnote b applies to
    every HDD row), so a piece without it would answer from the rows alone.
    """
    lines = block.split("\n")
    first_row = next(i for i, line in enumerate(lines) if is_table_line(line))
    caption, rows = lines[:first_row], lines[first_row:]
    n_header = _header_row_count(rows)
    header, _, body = table_rows.split_table(rows, n_header)
    labels = table_rows.row_labels(header, body)
    heading = table_rows.rows_heading(_caption_title(caption))
    body_lines = rows[n_header:]
    tail = [notes] if notes else []
    if labels is None or not any(labels):
        if count("\n".join([block] + tail)) <= chunk_size:
            return ["\n".join([block] + tail)]
        labels, heading = [None] * len(body_lines), ""
    whole = "\n".join(([block, heading] + [line for line in labels if line] if heading else [block]) + tail)
    if count(whole) <= chunk_size:
        return [whole]
    preamble = "\n".join(caption + rows[:n_header])
    budget = max(chunk_size - count(preamble) - (count(heading) + 1 if heading else 0)
                 - (count(notes) + 1 if notes else 0), 1)

    def cost(i: int) -> int:
        return count(body_lines[i]) + 1 + (count(labels[i]) + 1 if labels[i] else 0)

    units = table_rows.row_groups(body) if heading else [[i] for i in range(len(body_lines))]
    pieces: List[str] = []
    for piece in _pack(units, cost, budget):
        named = [labels[i] for i in piece if labels[i]]
        pieces.append("\n".join([preamble] + [body_lines[i] for i in piece] + ([heading] + named if named else [])
                                + tail))
    return pieces


def split_text(text: str, chunk_size: int, chunk_overlap: int, count: Optional[Callable[[str], int]] = None) -> List[str]:
    """Chunk text so that no Markdown table is cut mid-row or separated from its headers."""
    tokenizer = get_tokenizer()
    count = count or (lambda s: len(tokenizer(s)))
    prose_splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    chunks: List[str] = []
    carry = ""  # short prose (page headers) waiting to join the next table
    segments: List[Tuple[str, str, str]] = []  # (kind, text, the table's notes block or "")
    for kind, segment, notes in _segments(text):
        block = table_notes.notes_block(notes) if notes else ""
        if block and count(block) > chunk_size * _MAX_NOTES_SHARE:
            # Too long to repeat in every piece of the table: the notes stay prose after it, as before DAR-717.
            segments += [(kind, segment, ""), ("prose", "\n".join(notes), "")]
        else:
            segments.append((kind, segment, block))
    for kind, segment, block in segments:
        if kind == "prose":
            if count(segment) < _MIN_PROSE_TOKENS:
                carry = f"{carry}\n{segment}".strip()
                continue
            if carry:
                segment, carry = f"{carry}\n{segment}", ""
            chunks.extend(prose_splitter.split_text(segment))
        else:
            if carry:
                segment, carry = f"{carry}\n{segment}", ""
            chunks.extend(_split_table(segment, chunk_size, count, block))
    if carry:
        if chunks:
            chunks[-1] = f"{chunks[-1]}\n{carry}"
        else:
            chunks.append(carry)
    return [chunk for chunk in (c.strip() for c in chunks) if chunk]


class TableAwareSplitter(TextSplitter):
    """LlamaIndex node parser wrapping `split_text`."""

    chunk_size: int = Field(description="Target tokens per chunk.")
    chunk_overlap: int = Field(description="Token overlap between prose chunks.")
    _count: Callable[[str], int] = PrivateAttr()

    def __init__(self, chunk_size: int, chunk_overlap: int, **kwargs):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap, **kwargs)
        tokenizer = get_tokenizer()
        self._count = lambda s: len(tokenizer(s))

    def split_text(self, text: str) -> List[str]:
        return split_text(text, self.chunk_size, self.chunk_overlap, self._count)

    def _parse_nodes(self, nodes: Sequence[Any], show_progress: bool = False, **kwargs: Any) -> List[Any]:
        """Tag chunks holding a table `kind="table"` (DAR-652 chunk contract), kept out of the embedded text."""
        parsed = super()._parse_nodes(nodes, show_progress=show_progress, **kwargs)
        for node in parsed:
            if any(is_table_line(line) for line in node.get_content().split("\n")):
                node.metadata = {**node.metadata, "kind": "table"}
                node.excluded_embed_metadata_keys = [*node.excluded_embed_metadata_keys, "kind"]
                node.excluded_llm_metadata_keys = [*node.excluded_llm_metadata_keys, "kind"]
        return parsed
