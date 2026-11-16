"""Tables that continue across PDF pages, joined into one page Document before chunking (DAR-655).

The PDF reader (rag/loader.py) gives one Markdown Document per page, so a table
that runs over a page break arrives as two tables: the rows on page N under
their caption and header, and the rows on page N+1 under whatever pymupdf4llm
took for a header there (often the first data row, as in the Traffic Services
Legal Guide, one 706-page table). Chunked like that, a row on the second page
is searched and read without its column names, and a row split by the break
is never whole.

`merge_continued_tables` looks at each pair of consecutive pages of the same
document. When page N ends with a table (only running footers and page numbers
after it) and page N+1 starts with a table (only running headers, page numbers
or a "(continued)" caption before it), the two tables have the same column
count, and at least one merge signal holds, page N+1's leading table rows move
into page N's table:

  header   page N+1's first row(s) repeat page N's header row(s), as a
           manual reprints "Table 3-1 ... | DESIGN SPEED | ADT ..." on each page
           (the repeat is dropped);
  continued   a caption on page N+1 says "continued" / "(cont." / "cont'd";
  geometry    the table's box ends in the bottom BOTTOM_FRACTION of page N and
              a table's box starts in the top TOP_FRACTION of page N+1 (from
              the loader's `table_bboxes` metadata, when it has them).

The merged Document keeps page N's metadata and records the last page it holds
in `metadata["page_end"]`; a table over three or more pages chains (the Legal
Guide is one table over 706 pages). `page_span` then gives each chunk of it
the pages its own rows came from. What is
left of page N+1 stays a Document of its own, and a page absorbed whole is
dropped. `merge_decisions` returns the same decisions, with the reason for each,
for the quality report (docs/table-merge-check.md).
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from llama_index.core import Document

from rag.table_notes import trailing_notes
from rag.tables import _MAX_CAPTION_CHARS as MAX_CAPTION_CHARS
from rag.tables import _header_row_count, cells, clean_markdown_tables, is_separator, is_table_line

# A table whose box ends this close to the bottom of page N, and one whose box
# starts this close to the top of page N+1, are taken to be the same table
# (the corpus audit's "tabbot"/"tabtop" criteria: 166 candidate breaks in 60
# documents). Fractions of the page height. The audit's 10% at the bottom is
# widened to 15% (tuned on the 20 hand-checked breaks, docs/table-merge-check.md):
# pymupdf-layout's table box stops at the last row's text, above a running
# footer, so the Legal Guide's full-page tables end at 0.886-0.91 of the page.
BOTTOM_FRACTION = 0.15
TOP_FRACTION = 0.12
# Trailing lines of a page that are not part of its last table, and leading
# lines of the next page that are not part of its first: page numbers and short
# running heads ("Page 7 of 706", "10-165", "December 2023").
MAX_EDGE_LINE_CHARS = 40
# Longer running heads and footers ("NCDOT Traffic Services Legal Guide (revised
# 6/20/23)", 53 characters) are recognised by repeating, digits aside, on at
# least this many pages of the document.
MIN_RUNNING_PAGES = 3
MAX_RUNNING_CHARS = 100
# A caption line that marks a continued table: "Table 3 (continued)",
# "TABLE 2-1 (CONT.)", "Table 5 cont'd", "(Continued from previous page)".
# MUTCD tables say "(Sheet 2 of 4)" instead.
_CONTINUED = re.compile(r"\(\s*cont|\bcontinued\b|\bcont'd\b|\bcont\.|\bsheet\s+(?:[2-9]|\d\d+)\s+of\s+\d+", re.IGNORECASE)
# pymupdf4llm drops a column that is empty on the whole page, so the
# continuation of a table whose last column holds nothing on page N+1 (the
# Legal Guide's "TEPPL Topic" column, pp. 9-10) has one column fewer; its rows
# are padded back when a continued caption confirms the merge.
MAX_MISSING_COLUMNS = 1


@dataclass
class MergeDecision:
    """Why two consecutive pages were, or were not, joined."""

    source: str
    page: int
    next_page: int
    merged: bool
    reason: str
    signals: Dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {"source": self.source, "page": self.page, "next_page": self.next_page,
                "merged": self.merged, "reason": self.reason, "signals": dict(self.signals)}


def _page_number(doc: Document) -> Optional[int]:
    label = str(doc.metadata.get("page_label", ""))
    return int(label) if label.isdigit() else None


def _norm(line: str) -> str:
    """A line for comparison: no Markdown bold, one space between words, lower case."""
    return " ".join(line.replace("**", "").split()).lower()


def _norm_row(row: str) -> str:
    return "|".join(_norm(cell) for cell in cells(row))


def _digits_masked(line: str) -> str:
    return re.sub(r"\d", "#", _norm(line))


def running_lines(pages: Sequence[Document]) -> frozenset:
    """Lines (digits masked) that repeat on MIN_RUNNING_PAGES or more pages: running heads and footers."""
    seen: Dict[str, set] = {}
    for n, doc in enumerate(pages):
        for line in doc.text.split("\n"):
            stripped = line.strip()
            if not stripped or is_table_line(stripped) or len(stripped) > MAX_RUNNING_CHARS:
                continue
            seen.setdefault(_digits_masked(stripped), set()).add(n)
    return frozenset(key for key, where in seen.items() if len(where) >= MIN_RUNNING_PAGES)


def _is_edge_line(line: str, running: frozenset) -> bool:
    stripped = line.strip()
    # Measured without Markdown: "# **Establishing Operational Objectives**" is a 35-character running head.
    short = len(_norm(stripped).lstrip("# ")) <= MAX_EDGE_LINE_CHARS
    return not stripped or (not is_table_line(stripped) and (short or _digits_masked(stripped) in running))


# A page number on its own line: "37", "10-165", "iv", "Page 7 of 706".
_PAGE_NUMBER = re.compile(r"^(?:page\s+)?(?:\d+(?:[-–.]\d+)?|[ivxlc]+)(?:\s+of\s+\d+)?$", re.IGNORECASE)


def _is_footer_line(line: str, running: frozenset) -> bool:
    """A line left on a page after its table that may be dropped: blank, a page number or a running head/footer.

    Stricter than _is_edge_line, which also lets any short line through: a
    short line of prose after a joined table must stay in the build.
    """
    stripped = line.replace("**", "").strip()
    return not stripped or bool(_PAGE_NUMBER.match(stripped)) or _digits_masked(stripped) in running


def _column_count(rows: Sequence[str]) -> int:
    """The table's column count: the separator row's cells (it always has the full count)."""
    for row in rows:
        if is_separator(row):
            return len(cells(row))
    return len(cells(rows[0])) if rows else 0


def _tail_table(lines: List[str], running: frozenset) -> Optional[Tuple[int, int]]:
    """[start, end) of the table that ends page N, with only edge lines after it; None when the page ends otherwise."""
    end = len(lines)
    while end > 0 and _is_edge_line(lines[end - 1], running):
        end -= 1
    if end == 0 or not is_table_line(lines[end - 1]):
        return None
    start = end
    while start > 0 and is_table_line(lines[start - 1]):
        start -= 1
    return start, end


def _head_table(lines: List[str], running: frozenset, tail_caption: List[str]) -> Tuple[Optional[Tuple[int, int]], bool, Optional[str]]:
    """[start, end) of the table that starts page N+1, whether a "continued" caption precedes it, and why not.

    Before the table there may be edge lines, a continued caption or page N's
    own caption printed again; any other line means the page starts with prose.
    """
    continued = False
    start = 0
    while start < len(lines) and not is_table_line(lines[start]):
        line = lines[start]
        if _is_continued_caption(line):
            continued = True
        elif not _is_edge_line(line, running) and not _same_caption(line, tail_caption):
            return None, continued, "next page starts with prose"
        start += 1
    if start == len(lines):
        return None, continued, "no table on page +1"
    end = start
    while end < len(lines) and is_table_line(lines[end]):
        end += 1
    return (start, end), continued, None


# A continued caption names the table or is little more than the marker
# ("Table 2-1 (continued)", "(Continued)"); a sentence that happens to say
# "continued" is prose.
_CAPTION_START = re.compile(r"^\W*(?:table|exhibit|figure|sheet)\b", re.IGNORECASE)
MAX_BARE_CONTINUED_CHARS = 30
# ... or ends with the marker: "Initial List of Candidate Locations - continued"
# (interim-design-safety-pilot-program.pdf p.19).
_CONTINUED_AT_END = re.compile(r"(?:\(\s*cont[^)]*\)|[-–—:]\s*cont(?:inued|'d|\.)?)\W*$", re.IGNORECASE)


def _is_continued_caption(line: str) -> bool:
    text = _norm(line).lstrip("# ")
    return bool(_CONTINUED.search(text)) and (
        bool(_CAPTION_START.match(text)) or len(text) <= MAX_BARE_CONTINUED_CHARS or bool(_CONTINUED_AT_END.search(text)))


def _caption_label(line: str) -> str:
    """"table 6h-1" from "# **Table 6H-1.  Temporary Traffic Control Zone Warning Sign and Plaque Sizes**"; "" if not a caption."""
    text = _norm(line).lstrip("# ")
    if not _CAPTION_START.match(text):
        return ""
    return " ".join(text.split()[:2]).rstrip(".:")


def _same_caption(line: str, tail_caption: List[str]) -> bool:
    """Whether a line above the continuation is page N's caption printed again.

    The same table label is enough: part6.pdf reprints "Table 6H-1. ..." on
    each page and Chapter2c.pdf adds "(Sheet 4 of 4)".
    """
    if _norm(line) in tail_caption:
        return True
    label = _caption_label(line)
    return bool(label) and any(_caption_label(c) == label for c in tail_caption)


def _caption_lines(lines: List[str], table_start: int) -> List[str]:
    """Up to two short non-blank lines right above the table (rag.tables._segments takes the same as its caption)."""
    caption: List[str] = []
    i = table_start - 1
    while i >= 0 and len(caption) < 2:
        if not lines[i].strip():
            i -= 1
            continue
        if is_table_line(lines[i]) or len(lines[i]) > MAX_CAPTION_CHARS:
            break
        caption.insert(0, _norm(lines[i]))
        i -= 1
    return caption


def _repeated_header(tail_rows: List[str], head_rows: List[str]) -> int:
    """How many of the continuation's leading rows repeat the tail table's header rows."""
    tail_header = [r for r in tail_rows[:_header_row_count(tail_rows)] if not is_separator(r)]
    head_data = [r for r in head_rows if not is_separator(r)]
    k = 0
    while k < len(tail_header) and k < len(head_data) and _norm_row(head_data[k]) == _norm_row(tail_header[k]):
        k += 1
    return k


def _geometry(tail_meta: Dict, head_meta: Dict) -> Optional[bool]:
    """Whether the boxes say the table runs off the bottom of N onto the top of N+1; None without boxes."""
    tail_boxes, head_boxes = tail_meta.get("table_bboxes"), head_meta.get("table_bboxes")
    if not tail_boxes or not head_boxes:
        return None
    return max(b[3] for b in tail_boxes) >= 1 - BOTTOM_FRACTION and min(b[1] for b in head_boxes) <= TOP_FRACTION


def _pad(row: str, columns: int) -> str:
    values = cells(row)
    return "|" + "|".join(values + [""] * (columns - len(values))) + "|"


def _decide(tail_doc: Document, tail_meta: Dict, head_doc: Document, running: frozenset) -> Tuple[Optional[Tuple[List[str], List[str], str]], MergeDecision]:
    """The merge of two consecutive pages, if any: (page N's new lines, page N+1's remaining lines, reason)."""
    source = str(tail_doc.metadata.get("source", ""))
    # The last page already joined into tail_doc: a table over three pages is decided page by page.
    page = int(tail_doc.metadata.get("page_end") or _page_number(tail_doc) or 0)
    next_page = _page_number(head_doc) or 0
    tail_lines, head_lines = tail_doc.text.split("\n"), head_doc.text.split("\n")
    signals: Dict[str, object] = {}

    def no(reason: str):
        return None, MergeDecision(source, page, next_page, False, reason, signals)

    tail = _tail_table(tail_lines, running)
    if tail is None:
        return no("page does not end with a table")
    tail_caption = _caption_lines(tail_lines, tail[0])
    head, continued, why = _head_table(head_lines, running, tail_caption)
    signals["continued"] = continued
    if head is None:
        return no(why or "no table at the top of the next page")
    tail_rows, head_rows = tail_lines[tail[0]:tail[1]], head_lines[head[0]:head[1]]
    tail_columns, head_columns = _column_count(tail_rows), _column_count(head_rows)
    signals["columns"] = f"{tail_columns} vs {head_columns}"
    missing = tail_columns - head_columns
    if missing < 0 or missing > MAX_MISSING_COLUMNS:
        return no(f"column count {tail_columns} vs {head_columns}")
    repeated = _repeated_header(tail_rows, head_rows)
    signals["header"] = repeated > 0
    geometry = _geometry(tail_meta, head_doc.metadata)
    signals["geometry"] = geometry
    reasons = [name for name, on in (("header", repeated > 0), ("continued", continued), ("geometry", geometry)) if on]
    if not reasons:
        return no("no merge signal (header not repeated, no continued caption, boxes apart)")
    if missing:
        # A column fewer is only the dropped empty column when the page says the table goes on;
        # boxes at the page edges alone also fit a new, narrower table with its own header.
        if not continued:
            return no(f"column count {tail_columns} vs {head_columns} without a continued caption")
        signals["padded"] = missing
    moved = [r for r in head_rows if not is_separator(r)][repeated:]
    moved = [_pad(r, tail_columns) if missing else r for r in moved]
    table = clean_markdown_tables("\n".join(tail_rows + moved)).split("\n")
    # The notes under the continued part belong to the whole table (DAR-717): they move with its
    # rows, so the splitter finds them right under the joined table.
    notes, after_notes = trailing_notes(head_lines, head[1], "\n".join(table))
    new_tail = tail_lines[:tail[0]] + table + ([""] + notes if notes else []) + tail_lines[tail[1]:]
    # Lines above the continuation that are not page furniture or the table's
    # caption again (a short heading, say) stay with the rest of page N+1.
    kept = [line for line in head_lines[:head[0]]
            if not (_is_footer_line(line, running) or _is_continued_caption(line) or _same_caption(line, tail_caption))]
    remainder = kept + head_lines[after_notes if notes else head[1]:]
    return (new_tail, remainder, " + ".join(reasons)), MergeDecision(source, page, next_page, True, " + ".join(reasons), signals)


def _without_boxes(metadata: Dict) -> Dict:
    return {k: v for k, v in metadata.items() if k != "table_bboxes"}


def _run(pages: Sequence[Document]) -> Tuple[List[Document], List[MergeDecision]]:
    running = running_lines(pages)
    out: List[Document] = []
    decisions: List[MergeDecision] = []
    current: Optional[Document] = None  # the Document being extended; its text may already hold earlier pages' rows
    current_last_meta: Dict = {}  # metadata (boxes) of the last page merged into `current`
    for doc in pages:
        page = _page_number(doc)
        adjacent = (
            current is not None and page is not None
            and doc.metadata.get("source") == current.metadata.get("source")
            and page == int(current.metadata.get("page_end") or _page_number(current) or -2) + 1
        )
        if adjacent:
            merge, decision = _decide(current, current_last_meta, doc, running)
            decisions.append(decision)
            if merge is not None:
                new_tail, remainder, _ = merge
                current = Document(text="\n".join(new_tail), metadata={**current.metadata, "page_end": page})
                current_last_meta = doc.metadata
                # Only a running footer left ("Page 18 of 706" in the Legal Guide): the
                # page was all table, so the joined table can run on to the next page.
                if not all(_is_footer_line(line, running) for line in remainder):
                    out.append(current)
                    current = Document(text="\n".join(remainder).strip("\n"), metadata=_without_boxes(doc.metadata))
                    current_last_meta = doc.metadata
                continue
        if current is not None:
            out.append(current)
        current = Document(text=doc.text, metadata=_without_boxes(doc.metadata))
        current_last_meta = doc.metadata
    if current is not None:
        out.append(current)
    return out, decisions


def merge_continued_tables(pages: Sequence[Document]) -> List[Document]:
    """The page Documents with tables that continue over a page break joined (see the module docstring).

    `pages` are a loader's Documents in reading order, one per page, with
    `page_label` and `source` metadata and, when the loader was asked for
    them, `table_bboxes` (dropped from the result; the chunks don't need them).
    """
    return _run(pages)[0]


def merge_decisions(pages: Sequence[Document]) -> List[MergeDecision]:
    """The decision for every pair of consecutive pages, for the quality report."""
    return _run(pages)[1]


def _line_key(line: str) -> str:
    """A line for finding it on its original page: a table row by its non-empty cells (padding and spacing aside)."""
    if is_table_line(line):
        return "|".join(c for c in (_norm(cell) for cell in cells(line)) if c)
    return _norm(line)


def page_lines(pages: Sequence[Document]) -> Dict[int, set]:
    """Per page number, the keys of its lines, from the loader's Documents before merging."""
    out: Dict[int, set] = {}
    for doc in pages:
        number = _page_number(doc)
        if number is not None:
            out.setdefault(number, set()).update(_line_key(line) for line in doc.text.split("\n") if line.strip())
    return out


def page_span(text: str, lines_by_page: Dict[int, set], first: int, last: int) -> Tuple[int, Optional[int]]:
    """(page, page_end or None) of a chunk cut from a Document merged over pages first..last.

    Each line of the chunk is looked up on the original pages; a line found on
    exactly one of them places the chunk there. A row of the Legal Guide's page
    300 then cites page 300, not the page 1 where the joined table starts. A
    split table repeats page N's caption and header on every part
    (rag.tables), so the lines above the first table and the first row of each
    table block are skipped; the first part's own rows still place it on page
    N. With no line placed, the whole span is kept.
    """
    found = set()
    previous_was_table = False
    seen_table = False
    for line in text.split("\n"):
        if not line.strip() or is_separator(line):
            continue
        table = is_table_line(line)
        header = table and not previous_was_table
        previous_was_table = table
        seen_table = seen_table or table
        if header or not seen_table:
            continue
        key = _line_key(line)
        where = [n for n in range(first, last + 1) if key in lines_by_page.get(n, ())]
        if len(where) == 1:
            found.add(where[0])
    if not found:
        return first, last if last != first else None
    return min(found), (max(found) if max(found) != min(found) else None)
