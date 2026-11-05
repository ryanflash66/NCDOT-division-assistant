"""Table text fidelity: filled header spans, row labels, rotated labels and labelled rows (DAR-655).

pymupdf4llm renders a PDF table as a Markdown grid in which the text of a
spanning header is sliced by the column boundaries it crosses, a row label
printed once for a group of rows sits on the group's first row only, and a
label printed vertically beside the rows is cut into fragments that land in the
cells it overlaps. The TMP Design Manual's NC-PCB deflection tables (PDF p. 37
and 38) show all three:

    |**Imp**|**act Angle (degree)/**||**D**|**esign Sp **|**eed(mph**|**)**||
    |---|---|---|---|---|---|---|---|
    |**Maxi**|**mum Deflection (in)**|**30**|**40**|**50**|**60**|**70**|**80**|
    |**8**|**Impact Angle**|11.1|10.4|9.6|8.7|7.7|6.7|
    ||**Maximum Deflection**|23.00|25.86|28.04|31.86|35.72|39.12|
    ...
    |**ft)**<br>**32**|**Impact Angle**|13.3|13.0|12.7|12.4|12.1|11.8|
    |**et (**<br>|**Maximum Deflection**|28.56|30.71|35.99|38.82|41.56|44.38|

The rotated row header "Offset (ft)" is intact in the page's text layer (one
line with dir (0, -1)); only the grid loses it. A model reading the row "14"
on its own cannot tell what 14 is, nor which design speed 27.42 belongs to.

The functions here work on the lines of one pipe table (`rows`) and are
applied by `rag.tables.clean_markdown_tables` (the grid) and
`rag.tables.split_text` (the labelled rows after each grid):

- `unstack_rows`: two rows pymupdf4llm stacked into one with `<br>` become two rows again.
- `strip_rotated_fragments` / `label_column`: the fragments of a rotated label
  are removed from the cells and the label becomes the column's header.
- `fill_header_spans`: sliced header titles are rejoined and written into every
  column they span; an empty header cell under a filled one inherits it.
- `fill_row_labels`: a body row with an empty first cell inherits the row label above.
- `header_paths` / `row_labels`: one line per body row naming every value by
  its column's header path, e.g. "Offset (ft)=14 | ... | Design Speed(mph): 40=27.42, ...".
"""

import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

Grid = List[List[str]]

_BOLD = re.compile(r"^\s*\*\*(.*?)\*\*\s*$", re.DOTALL)
_SEPARATOR_CELL = re.compile(r"^\s*:?-{3,}:?\s*$")
# A sliced word: the left cell ends in a letter and the right one starts with a
# lowercase letter ("Imp" | "act Angle", "D" | "esign Sp"), or a bracket is
# left open on one side and closed on the other ("eed(mph" | ")").
_ENDS_WITH_LETTER = re.compile(r"[A-Za-z]$")
_STARTS_LOWER = re.compile(r"^[a-z]")
# A data value: a number, range or placeholder ("25.16", "12 - 14", "-", "10:1").
_NUMBER = re.compile(r"^[\d.,:\-\u2013*~<>%$/ ]+$")
# Labelled rows are skipped for very wide tables (the lines would be longer
# than the grid rows they explain) and for tables whose headers stay mostly
# empty after filling (the lines would name columns "Column 7").
MAX_LABELLED_COLUMNS = 12
MAX_EMPTY_HEADER_SHARE = 0.5
# A two-column table already reads as "label | value"; the lines would only repeat it.
MIN_LABELLED_COLUMNS = 3
# Longest first-column cell for that column to count as row labels (see fill_row_labels).
MAX_ROW_LABEL_CHARS = 40
# Rotated lines checked per page: a landscape page set sideways has every line
# rotated, and none of those is a label beside a table.
MAX_ROTATED_LABELS = 40


# ---------------------------------------------------------------------------
# Cells and rows
# ---------------------------------------------------------------------------

def cells(line: str) -> List[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return inner.split("|")


def row(values: Sequence[str]) -> str:
    return "|" + "|".join(values) + "|"


def is_separator(line: str) -> bool:
    values = cells(line)
    return bool(values) and all(_SEPARATOR_CELL.match(cell) for cell in values)


def plain(cell: str) -> str:
    """The cell's text without bold marks or surrounding space."""
    match = _BOLD.match(cell)
    text = match.group(1) if match else cell
    return re.sub(r"\s+", " ", text).strip()


def _styled(text: str, like: Sequence[str]) -> str:
    """`text` in bold when every non-empty cell it replaces was bold."""
    sources = [cell for cell in like if cell.strip()]
    if text and sources and all(_BOLD.match(cell) for cell in sources):
        return f"**{text}**"
    return text


def _grid(rows: Sequence[str]) -> Grid:
    return [cells(line) for line in rows]


def _lines(grid: Grid) -> List[str]:
    return [row(values) for values in grid]


def _rectangular(grid: Grid) -> bool:
    return bool(grid) and all(len(values) == len(grid[0]) for values in grid)


def split_table(rows: Sequence[str], n_header: int) -> Tuple[Grid, Optional[str], Grid]:
    """(header rows, separator line, body rows) for the table's lines and header row count."""
    head = list(rows[:n_header])
    separator = next((line for line in head if is_separator(line)), None)
    header = _grid(line for line in head if not is_separator(line))
    return header, separator, _grid(rows[n_header:])


# ---------------------------------------------------------------------------
# Rows stacked with <br>
# ---------------------------------------------------------------------------

def unstack_rows(rows: List[str]) -> List[str]:
    """Split a row that holds two rows' values stacked with `<br>` back into two rows.

    TMP p. 37, the 14 ft offset: pymupdf4llm put both of the group's rows into
    one, "**Impact Angle**<br>**Maximum Deflection**" over "12.7<br>25.16", and
    the loader used to turn the `<br>` into a space, so the row read as two
    numbers per cell. A body row is unstacked when more cells have the same
    number of `<br>` parts, all non-empty, than have fewer, and most of those
    cells hold only numbers: a wrapped header ("Design<br>Speed [mph]") or a
    sentence wrapped in two cells ("Place at<br>50 ft") is one row whose
    lines the loader joins with a space, as is a lone wrapped cell
    ("10 inches<br>(informal)").
    """
    out: List[str] = []
    first_body = 2 if len(rows) > 1 and is_separator(rows[1]) else 0
    for n, line in enumerate(rows):
        if "<br>" not in line or n < first_body:
            out.append(line)
            continue
        parts = [cell.split("<br>") for cell in cells(line)]
        k = max(len(p) for p in parts)
        stacked = [p for p in parts if len(p) == k]
        others = [p for p in parts if len(p) < k and any(s.strip() for s in p)]
        numeric = [p for p in stacked if all(_NUMBER.match(plain(s)) for s in p)]
        if k < 2 or len(stacked) < 2 or len(stacked) <= len(others) or not all(s.strip() for p in stacked for s in p) \
                or 2 * len(numeric) < len(stacked):
            out.append(line)
            continue
        for t in range(k):
            out.append(row([p[t] if len(p) == k else (p[0] if t == 0 else "") for p in parts]))
    return out


# ---------------------------------------------------------------------------
# Rotated labels
# ---------------------------------------------------------------------------

def _tiles(parts: Sequence[str], target: str) -> bool:
    joined = "".join(parts)
    return joined == target or "".join(reversed(parts)) == target


def strip_rotated_fragments(rows: List[str], rotated: Sequence[str]) -> Tuple[List[str], Dict[int, str]]:
    """Remove the fragments of each rotated label from the cells and say which column held them.

    A label printed vertically beside a table ends up sliced by row into
    `<br>`-separated cell parts ("ft)", "et (", "ffs", "O" down column 0 of
    TMP p. 37). The parts are recognised when, read down (or up) the column,
    they tile the rotated string exactly over two or more rows; a lone "O" in
    some other cell, or a cell that reads like the whole line, never matches. Returns the rows without the fragments and {column: label} for
    `label_column`, applied once the header spans are filled.
    """
    found: Dict[int, str] = {}
    if not rotated or len(rotated) > MAX_ROTATED_LABELS:
        return rows, found
    grid = [[cell.split("<br>") for cell in cells(line)] for line in rows]
    width = max((len(values) for values in grid), default=0)
    for label in rotated:
        target = re.sub(r"\s+", "", label)
        if len(target) < 3 or not re.search(r"[A-Za-z]", target):
            continue
        for column in range(width):
            candidates: List[Optional[Tuple[int, int]]] = []  # (row, part) or None per row
            for r, values in enumerate(grid):
                parts = values[column] if column < len(values) else []
                hits = [i for i, part in enumerate(parts)
                        if re.sub(r"\s+", "", plain(part)) and re.sub(r"\s+", "", plain(part)) in target]
                candidates.append((r, hits[0]) if len(hits) == 1 else None)
            matched = _tiling_run(candidates, grid, column, target)
            if matched is None:
                continue
            for r, i in matched:
                grid[r][column].pop(i)
                if not any(part.strip() for part in grid[r][column]):
                    grid[r][column] = [""]
            found[column] = re.sub(r"\s+", " ", label).strip()
            break
    out = [row(["<br>".join(parts) for parts in values]) for values in grid]
    return out, found


def _tiling_run(candidates: List[Optional[Tuple[int, int]]], grid, column: int, target: str) -> Optional[List[Tuple[int, int]]]:
    """The consecutive rows whose candidate parts tile `target`, or None."""
    for start, first in enumerate(candidates):
        if first is None:
            continue
        run: List[Tuple[int, int]] = []
        for hit in candidates[start:]:
            if hit is None:
                break
            run.append(hit)
            parts = [re.sub(r"\s+", "", plain(grid[r][column][i])) for r, i in run]
            # A single cell equal to a rotated line is a value or a column header
            # (on a page set sideways every line is rotated), not a scattered label.
            if len(run) > 1 and _tiles(parts, target):
                return run
    return None


def label_column(rows: List[str], n_header: int, found: Dict[int, str]) -> List[str]:
    """Make each rotated label the header of the column that held its fragments.

    The label replaces the column's header cells when they are empty or merely
    repeat the neighbouring column's (TMP p. 37: the corner title "Impact Angle
    (degree)/ Maximum Deflection (in)" spans columns 0 and 1 and describes the
    row type in column 1, while the rotated "Offset (ft)" is what column 0
    holds). A column with a header of its own keeps it.
    """
    if not found:
        return rows
    header, separator, body = split_table(rows, n_header)
    if not _rectangular(header):
        return rows
    width = len(header[0])
    for column, label in found.items():
        if column >= width:
            continue
        own = [values[column] for values in header]
        neighbours = [c for c in (column - 1, column + 1) if 0 <= c < width]
        duplicate = any(all(plain(values[column]) == plain(values[c]) for values in header) for c in neighbours)
        if all(not plain(cell) for cell in own) or duplicate:
            for values in header:
                values[column] = _styled(label, own)
    return _lines(header[:1]) + ([separator] if separator else []) + _lines(header[1:]) + _lines(body)


# ---------------------------------------------------------------------------
# Header spans
# ---------------------------------------------------------------------------

def _sliced(left: str, right: str) -> bool:
    """Whether a word or bracket runs across the boundary between two cells."""
    a, b = plain(left), plain(right)
    if not a or not b:
        return False
    if _ENDS_WITH_LETTER.search(a) and _STARTS_LOWER.match(b):
        return True
    joined = a + b
    for open_, close in ("()", "[]"):
        if (a.count(open_) > a.count(close) or b.count(close) > b.count(open_)) \
                and joined.count(open_) == joined.count(close):
            return True
    return False


def _runs(values: List[str]) -> List[Tuple[int, int, str, bool]]:
    """(first column, last column, joined title, sliced) for each run of non-empty cells."""
    runs: List[Tuple[int, int, str, bool]] = []
    i = 0
    while i < len(values):
        if not plain(values[i]):
            i += 1
            continue
        j, sliced = i, False
        while j + 1 < len(values) and _sliced(values[j], values[j + 1]):
            j, sliced = j + 1, True
        title = "".join(plain(v) for v in values[i:j + 1]) if sliced else plain(values[i])
        runs.append((i, j, re.sub(r"\s+", " ", title).strip(), sliced))
        i = j + 1
    return runs


def _fill_spans_in_row(values: List[str], below: Optional[List[str]]) -> List[str]:
    """Write each header title into every column it spans.

    A row with a sliced title had its text placed by position: a title is
    centred over its span, so it claims as many empty cells on each side as
    the narrower side has ("D|esign Sp|eed(mph|)" with one empty cell either
    side spans all six speed columns; "Angle of||" claims nothing). A row
    without sliced titles came from detected merged cells, whose text sits in
    the span's first cell, so an empty cell inherits the cell to its left when
    both columns have a sub-header in the row `below` ("|Item|Design Speed|||"
    over "||30|40|50|"); not in the last header row (`below` is None), where an
    empty cell is a column with no header ("|Speed|Width||" over data), nor
    over a column whose own header sits lower ("|Type|Width||" over "|||Remarks|").
    """
    runs = _runs(values)
    out = list(values)
    if any(sliced for _, _, _, sliced in runs):
        for n, (i, j, title, _) in enumerate(runs):
            left_gap = i - (runs[n - 1][1] + 1 if n else 0)
            right_gap = (runs[n + 1][0] if n + 1 < len(runs) else len(values)) - (j + 1)
            claim = min(left_gap, right_gap)
            text = _styled(title, values[i:j + 1])
            for c in range(i - claim, j + claim + 1):
                out[c] = text
    elif below is not None:
        for c in range(1, len(values)):
            if not plain(out[c]) and plain(out[c - 1]) and plain(below[c]) and plain(below[c - 1]):
                out[c] = out[c - 1]
    return out


def fill_header_spans(rows: List[str], n_header: int) -> List[str]:
    """Rejoin sliced header titles and fill column and row spans in the header rows.

    After the column spans (see `_fill_spans_in_row`), an empty header cell
    under a filled one inherits it, so every column reads top to bottom as
    its header path. Rows of unequal width are left alone.
    """
    header, separator, body = split_table(rows, n_header)
    if not header or not _rectangular(header):
        return rows
    filled = [_fill_spans_in_row(values, header[r + 1] if r + 1 < len(header) else None)
              for r, values in enumerate(header)]
    for r in range(1, len(filled)):
        for c, cell in enumerate(filled[r]):
            if not plain(cell) and plain(filled[r - 1][c]):
                filled[r][c] = filled[r - 1][c]
    return _lines(filled[:1]) + ([separator] if separator else []) + _lines(filled[1:]) + _lines(body)


# ---------------------------------------------------------------------------
# Row labels
# ---------------------------------------------------------------------------

def fill_row_labels(rows: List[str], n_header: int) -> List[str]:
    """Write the row label above into a body row whose first cell is empty.

    TMP p. 37 prints each offset once for its pair of rows (Impact Angle,
    Maximum Deflection); Table 3 of the At Grade Intersections chapter prints
    the turn angle on the first vehicle's row only. The first column is taken
    as the label column when the first body row has one. A row without data
    values is left as it is.
    """
    header, separator, body = split_table(rows, n_header)
    if not body or not plain(body[0][0]):
        return rows
    # A first column of sentences is a description column, not row labels: an
    # empty cell there is a row without a description, and copying the one
    # above would state something the table doesn't.
    if any(len(plain(values[0])) > MAX_ROW_LABEL_CHARS for values in body):
        return rows
    label = body[0][0]
    for values in body:
        filled = [plain(cell) for cell in values[1:] if plain(cell)]
        if plain(values[0]):
            label = values[0]
        # Only a row of values belongs to the label above: a row of words with
        # an empty first cell is a wrapped line or a note ("||placed at 50 ft
        # intervals|"), and labelling it would state a second fact.
        elif filled and 2 * sum(1 for cell in filled if _NUMBER.match(cell)) >= len(filled):
            values[0] = label
    return list(rows[:n_header]) + _lines(body)


# ---------------------------------------------------------------------------
# Header paths and labelled rows
# ---------------------------------------------------------------------------

def header_paths(header: Grid) -> List[List[str]]:
    """Each column's header path, top to bottom: group titles, then the column's own header.

    A cell in a row above the last that repeats its neighbour's is a title
    spanning both columns (a group level); the other cells of a column are the
    lines of its own header, wrapped over rows ("Angle of" / "Turn" /
    "(Degrees)" is one header). The corner convention "A \\ B" of
    `rag.tables._merge_spanning_header` names the first column A and puts
    the other columns under B.
    """
    if not header or not _rectangular(header):
        return [[] for _ in (header[0] if header else [])]
    width = len(header[0])
    paths: List[List[str]] = []
    for c in range(width):
        levels: List[str] = []
        own: List[str] = []
        for r, values in enumerate(header):
            text = plain(values[c])
            if not text:
                continue
            shared = r < len(header) - 1 and any(
                plain(values[n]) == text for n in (c - 1, c + 1) if 0 <= n < width)
            if shared:
                if not levels or levels[-1] != text:
                    levels.append(text)
            else:
                own.append(text)
        leaf = " ".join(dict.fromkeys(own))
        paths.append(levels + ([leaf] if leaf else []))
    if paths and len(paths[0]) == 1 and " \\ " in paths[0][0]:
        first, rest = (part.strip() for part in paths[0][0].split(" \\ ", 1))
        paths[0] = [first]
        paths[1:] = [[rest] + path if len(path) == 1 else path for path in paths[1:]]
    return paths


def _join(path: Sequence[str]) -> str:
    """A path as text: levels joined with " > ", or with a space after a level that ends in "/" or "-"."""
    text = ""
    for part in path:
        if not text:
            text = part
        elif text.endswith(("/", "-")):
            text = f"{text} {part}"
        else:
            text = f"{text} > {part}"
    return text


def row_labels(header: Grid, body: Grid) -> Optional[List[Optional[str]]]:
    """For each body row, the line naming each of its values by its column's header path.

    Columns under the same group title are listed together after it:

        Offset (ft)=14 | Impact Angle (degree)/ Maximum Deflection (in)=Maximum Deflection | Design Speed(mph): 30=25.16, 40=27.42, ...

    Empty values are left out; a row with no values, or of another width than
    the header, gets None. Returns None (and logs why) for tables wider than
    MAX_LABELLED_COLUMNS, narrower than MIN_LABELLED_COLUMNS, or whose header
    cells are mostly empty after filling.
    """
    if not header or not _rectangular(header) or not body:
        return None
    width = len(header[0])
    if width > MAX_LABELLED_COLUMNS or width < MIN_LABELLED_COLUMNS:
        log.debug("no labelled rows: %d columns (%s)", width, header[0][:3])
        return None
    empty = sum(1 for values in header for cell in values if not plain(cell))
    if empty > MAX_EMPTY_HEADER_SHARE * width * len(header):
        log.debug("no labelled rows: %d of %d header cells empty (%s)", empty, width * len(header), header[0][:3])
        return None
    paths = header_paths(header)
    lines: List[Optional[str]] = []
    for values in body:
        groups: List[Tuple[Optional[str], List[str]]] = []
        for c, cell in enumerate(values if len(values) == width else []):
            value = plain(cell)
            if not value:
                continue
            path = paths[c] or [f"Column {c + 1}"]
            parent = _join(path[:-1]) if len(path) > 1 else None
            # A header that lists the row types names the value already: TMP p. 37's
            # corner "Impact Angle (degree)/ Maximum Deflection (in)" over "Maximum
            # Deflection". The value alone says it in a third of the tokens, which
            # lets two offsets share a 512-token piece.
            named = " " in value and not re.search(r"\d", value) and value.lower() in path[-1].lower()
            item = value if named else f"{path[-1]}={value}"
            if parent is not None and groups and groups[-1][0] == parent:
                groups[-1][1].append(item)
            else:
                groups.append((parent, [item]))
        lines.append(" | ".join(f"{parent}: {', '.join(items)}" if parent else items[0]
                                for parent, items in groups) or None)
    return lines


def rows_heading(caption: str = "") -> str:
    """The line that introduces the labelled rows after a grid."""
    return f"Rows ({caption}):" if caption else "Rows:"


def row_groups(body: Grid) -> List[List[int]]:
    """Body row indexes grouped by equal first cell, so a split keeps a label's rows together."""
    groups: List[List[int]] = []
    for i, values in enumerate(body):
        key = plain(values[0]) if values else ""
        if groups and key and plain(body[groups[-1][0]][0]) == key:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups
