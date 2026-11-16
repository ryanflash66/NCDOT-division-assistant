"""Notes printed under a table, kept with the table they explain (DAR-717).

Footnote questions were the one question type that got worse in the redo
(docs/redo-methods.md, section 3.2): the right page was found and cited, but the
answer came from the table body, because the note under the table never reached
the model beside it. The note was lost in three ways
(docs/redo-reports/dar-717-footnotes.md):

- FHWA road user cost report p.50: "Note: Reported for work zones with active
  work and temporary lane closure." sits under Table 24, but the splitter took
  the short lines above the next table as that table's caption, so the note
  went to Table 25's chunks and Table 24's chunk had none.
- UAM p.101 and the FHWA report p.41: the notes under Table 3-1 ("b ... The
  minimum cover depth for transverse HDD installations of any size on fully
  controlled access roadways is 15 feet") and Table 12's "Source: ... Current
  year CPI: 193.396" began the next prose chunk, apart from the table.
- Standard Specifications p.580: the table is set sideways, and pymupdf4llm's
  Markdown leaves out its note "A. Use a 5% acetic acid solution ..." although
  the page's text layer has it.

The splitter (rag.tables) now takes the note lines right under a table into the
table's chunks as a "Notes:" block, the loader puts back a note line the
Markdown dropped (`missing_notes`), and a joined table (rag.table_merge) takes
the notes under its continued part with it.
"""

import re
import unicodedata
from typing import List, Optional, Sequence, Tuple

# The line that opens the notes block in a table chunk; prototype.ingest tags such chunks `notes`.
NOTES_HEADING = "Notes:"

# A bullet and bold/italic marks pymupdf4llm may put before a note's marker ("- **a**", "**Note:**").
_LEAD = r"^\s*(?:[-•]\s+)?(?:\*\*|__)?\s*"
_END = r"(?:\*\*|__)?"
# "Note:", "NOTES:", "Note.", "Source:" (FHWA p.50 Table 24, p.41 Table 12).
_NOTE_WORD = re.compile(_LEAD + r"(?:notes?|sources?)\s*" + _END + r"\s*[:.]", re.IGNORECASE)
# A letter marker with a period or parenthesis: "A. Use a 5% acetic acid ..." (Standard Specifications
# p.580), "a) ...". Not "(A) General": the specifications number their subsections that way.
_LETTER_MARK = re.compile(_LEAD + r"[A-Za-z]" + _END + r"[.)]" + _END + r"\s+\S")
# A lower-case letter marker and a capitalised word: "a Auger is limited to 6” or less" (UAM p.101).
_LOWER_MARK = re.compile(_LEAD + r"[a-z]" + _END + r"\s+[A-Z]")
# A superscript marker as pymupdf4llm writes it ("<sup>a</sup> Auger ..."), or a dagger-style symbol.
_SUP_MARK = re.compile(_LEAD + r"<sup>\s*[A-Za-z0-9*†‡§]{1,2}\s*</sup>\s*\S")
# A footnote asterisk needs a space after it, so an italic line ("*Figure 3*") is not taken for one.
_SYMBOL_MARK = re.compile(_LEAD + r"(?:\\?\*\s+|[†‡§]\s*)[A-Za-z0-9(]")
# Numbered notes ("1. ...") count only under a "Notes:" line: otherwise they are a numbered list.
_NUMBER_MARK = re.compile(_LEAD + r"\d{1,2}" + _END + r"[.)]" + _END + r"\s+\S")
# A line this long is a paragraph, not a note; and a run of notes this long is prose about the table.
_MAX_NOTE_CHARS = 600
_MAX_NOTE_LINES = 8
# Text-layer lines shorter than this are cell values and labels, not notes worth recovering.
_MIN_RECOVERED_CHARS = 15


# The letter of a lettered note: "A. ...", "a ...", "<sup>b</sup> ...".
_MARKER_LETTER = re.compile(_LEAD + r"(?:<sup>\s*)?([A-Za-z])")


def _marker(text: str) -> Optional[str]:
    """The letter a lettered note line starts with, or None for "Note:", "Source:", "*" and "†" lines."""
    if _NOTE_WORD.match(text) or _SYMBOL_MARK.match(text):
        return None
    if _LETTER_MARK.match(text) or _LOWER_MARK.match(text) or _SUP_MARK.match(text):
        match = _MARKER_LETTER.match(text)
        return match.group(1) if match else None
    return None


def _referenced(letter: str, table: str) -> bool:
    """Whether the table marks a cell with this letter: "Pigments**A**", "Auger<sup>a</sup>"."""
    mark = re.escape(letter)
    return bool(re.search(rf"\*\*\s*{mark}\s*\*\*|<sup>\s*{mark}\s*</sup>", table))


def is_note_line(line: str, numbered: bool = False, table: Optional[str] = None) -> bool:
    """Whether a line reads as a note under a table: "Note: ...", "Source: ...", "a ...", "A. ...", "* ...".

    `numbered` also accepts "1. ..." (under a "Notes:" line). Headings, table
    rows and long paragraphs are never notes. With the `table` text given, a
    lettered line counts only when the table marks a cell with its letter:
    the TMP strategies matrix (trans_mgmt_plans.pdf pp.84-126) is followed by
    headings "A. Control Strategies", and the FHWA road user cost report lists
    "o Pickups & vans" with a hollow bullet "o"; neither table has such a mark.
    """
    text = line.strip()
    if not text or text.startswith(("#", "|", ">")) or len(text) > _MAX_NOTE_CHARS:
        return False
    if any(p.match(text) for p in (_NOTE_WORD, _LETTER_MARK, _LOWER_MARK, _SUP_MARK, _SYMBOL_MARK)):
        letter = _marker(text)
        return letter is None or table is None or _referenced(letter, table)
    return numbered and bool(_NUMBER_MARK.match(text))


def _opens_numbered_notes(line: str) -> bool:
    """A "Notes:" line with nothing after it: numbered notes follow."""
    return bool(re.fullmatch(_LEAD + r"notes?\s*" + _END + r"\s*:?\s*" + _END + r"\s*", line, re.IGNORECASE))


def trailing_notes(lines: Sequence[str], start: int, table: Optional[str] = None) -> Tuple[List[str], int]:
    """The note lines right under a table that ends at `lines[start]`, and the index after them.

    `table` is the table's own text (see is_note_line). Blank lines between the
    table and its notes are skipped; the notes end at the first line that is
    not a note. ([], start) when no note follows, or only a bare "Note:" line
    whose text is not a note (the Signal Timing Manual's "Note:" above prose).
    """
    notes: List[str] = []
    numbered = False
    i, end = start, start
    while i < len(lines) and len(notes) < _MAX_NOTE_LINES:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if not is_note_line(line, numbered, table):
            break
        numbered = numbered or _opens_numbered_notes(line)
        notes.append(line.strip())
        i += 1
        end = i
    if all(_opens_numbered_notes(n) for n in notes):
        return [], start
    return notes, end


def _clean(line: str) -> str:
    """A note line without its list bullet."""
    return re.sub(r"^[-•]\s+", "", line.strip())


def notes_block(notes: Sequence[str]) -> str:
    """The notes as the block that follows the table in each of its chunks."""
    return "\n".join([NOTES_HEADING] + [_clean(n) for n in notes])


def has_notes(text: str) -> bool:
    """Whether a chunk carries a table's notes block: a "Notes:" line in a chunk with table rows.

    A prose chunk with its own "Notes:" heading is not tagged, so it gets no
    "footnote" boost in the keyword field.
    """
    lines = text.split("\n")
    return NOTES_HEADING in lines and any(line.lstrip().startswith("|") for line in lines)


# Ligature glyphs ("ﬁ", "ﬂ"): the text layer keeps them where pymupdf4llm's Markdown spells the letters out.
_LIGATURES = re.compile("[ﬀ-ﬆ]")


def _letters(text: str) -> str:
    """Letters and digits only, lower case, without HTML tags: what survives pymupdf4llm's markup."""
    text = _LIGATURES.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)
    return re.sub(r"[^a-z0-9]", "", re.sub(r"<[^>]+>", "", text.lower()))


def missing_notes(markdown: str, text_lines: Sequence[str]) -> List[str]:
    """Note lines of the page's text layer that its Markdown left out (Standard Specifications p.580).

    A note counts as missing when its letters and digits appear nowhere in the
    Markdown. A note the text layer wraps onto further lines takes those lines
    too, while they are also missing and don't start another note.
    """
    if not any(line.lstrip().startswith("|") for line in markdown.split("\n")):
        return []
    present = _letters(markdown)
    lines = [" ".join(line.split()) for line in text_lines]
    found: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        key = _letters(line)
        if len(line) < _MIN_RECOVERED_CHARS or not key or key in present:
            continue
        if not (_NOTE_WORD.match(line) or _LETTER_MARK.match(line) or _LOWER_MARK.match(line)):
            continue
        letter = _marker(line)
        if letter and not _referenced(letter, markdown):
            continue
        while i < len(lines) and lines[i] and _letters(lines[i]) not in present and not is_note_line(lines[i]):
            line = f"{line} {lines[i]}"
            i += 1
        found.append(line)
    return found[:_MAX_NOTE_LINES]


def insert_after_last_table(markdown: str, notes: Sequence[str]) -> str:
    """The Markdown with these note lines right under its last table, where the splitter takes them as its notes."""
    lines = markdown.split("\n")
    last = max((i for i, line in enumerate(lines) if line.lstrip().startswith("|")), default=None)
    if last is None or not notes:
        return markdown
    return "\n".join(lines[:last + 1] + [""] + list(notes) + lines[last + 1:])
