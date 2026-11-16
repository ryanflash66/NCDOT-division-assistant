"""Notes under a table kept with the table (rag/table_notes.py, rag/tables.py, rag/table_merge.py; DAR-717)."""

import pytest
from llama_index.core import Document

from rag import table_notes, tables
from rag.table_merge import merge_continued_tables


def _count(text: str) -> int:
    return len(text.split())


# FHWA road user cost report p.50: a note between two tables.
FHWA_P50 = "\n".join([
    "Table 24. Typical work zone crash modification factors for temporary lane closure on freeways.",
    "|**Crash Types**|**Crash Severity**|**CMF**|",
    "|---|---|---|",
    "|All|All|1.77|",
    "|Nighttime|All|1.57|",
    "",
    "Note: Reported for work zones with active work and temporary lane closure.",
    "",
    "Table 25. Average crash rates at Interstate work zones in Indiana.",
    "|**Sites**|**CMF**|",
    "|---|---|",
    "|Sites Using Cross-over|1.33|",
])

# UAM p.101: lettered notes under Table 3-1, then prose.
UAM_NOTES = [
    "- a Auger is limited to 6” or less in diameter.",
    "- b The minimum cover depth for transverse HDD installations of any size on fully controlled access "
    "roadways is 15 feet.",
    "- c The minimum cover depth for HDD installations of pipe greater than 36 inches in diameter shall be 15 feet.",
]


def _uam(rows: int) -> str:
    body = [f"|HDD<sup>b</sup>|{d}–{d + 4}|{d} feet|" for d in range(rows)]
    return "\n".join([
        "**Table 3-1. Minimum Bury Depths using Trenchless Methods**",
        "|**Method**|**Diameter**|**Minimum Depth of Cover**|",
        "|---|---|---|",
        "|Bore and Jack or Auger<sup>a</sup>|Any size|3 feet|",
        *body,
        "|HDD<sup>b</sup>|>15–36<sup>c</sup>|15 feet|",
        "",
        *UAM_NOTES,
        "",
        "Regardless of which trenchless method is used, the minimum depth for crossing under ditches is 2 feet "
        "under the unsilted original ditchline. " * 3,
    ])


def test_a_note_between_two_tables_stays_with_the_table_above():
    chunks = tables.split_text(FHWA_P50, chunk_size=300, chunk_overlap=0, count=_count)

    table_24 = next(c for c in chunks if "Table 24" in c)
    table_25 = next(c for c in chunks if "Table 25" in c)
    assert "Notes:\nNote: Reported for work zones with active work and temporary lane closure." in table_24
    assert "active work" not in table_25
    assert table_25.startswith("Table 25.")  # its caption, without the note above it


def test_notes_end_every_piece_of_a_split_table_and_leave_the_prose():
    chunks = tables.split_text(_uam(60), chunk_size=200, chunk_overlap=0, count=_count)

    pieces = [c for c in chunks if "|---|" in c]
    assert len(pieces) > 1
    for piece in pieces:
        assert piece.split("\n")[-4:] == ["Notes:"] + [n[2:] for n in UAM_NOTES]
        assert table_notes.has_notes(piece)
    prose = [c for c in chunks if "|---|" not in c]
    assert prose and all("fully controlled access" not in c for c in prose)
    assert any("unsilted original ditchline" in c for c in prose)


def test_notes_too_long_to_repeat_stay_prose_after_the_table():
    long_note = "- a " + "This note goes on and on. " * 40
    text = "|A|B|\n|---|---|\n|1|2|\n\n" + long_note
    chunks = tables.split_text(text, chunk_size=200, chunk_overlap=0, count=_count)

    assert chunks[0] == "|A|B|\n|---|---|\n|1|2|"
    assert "goes on and on" in chunks[1]


def test_numbered_lines_are_notes_only_under_a_notes_line():
    numbered = ["1. Use the higher value.", "2. Interpolate between rows."]
    assert table_notes.trailing_notes(["", *numbered], 0) == ([], 0)
    notes, end = table_notes.trailing_notes(["", "**Notes:**", *numbered, "", "More prose follows here."], 0)
    assert notes == ["**Notes:**", *numbered] and end == 4


@pytest.mark.parametrize("line", [
    "Note: Reported for work zones with active work and temporary lane closure.",
    "**NOTES:** Speeds are posted speeds.",
    "Source: FHWA’s RealCost and NCHRP Report 133. Current year CPI: 193.396 (year 2010)",
    "- a Auger is limited to 6” or less in diameter.",
    "A. Use a 5% acetic acid solution with a pH 4 + 2 to determine solubility.",
    "b) Applies to freeways only.",
    "<sup>c</sup> The minimum cover depth shall be 15 feet.",
    "* Speeds in mph.",
    "† Or approved equivalent.",
])
def test_note_lines(line):
    assert table_notes.is_note_line(line)


@pytest.mark.parametrize("line", [
    "- **(C) Inspection**",  # the Standard Specifications' subsection headings
    "##### (3) Color",
    "|1|2|",
    "The colors before and after weathering are compared with AMS-STD-595.",
    "A work zone is an area of a highway with construction, maintenance or utility work activities.",
    "*Figure 3 Detour route*",
    "1. Set up the advance warning signs.",
    "> 44 Pal, R., and K. Sinha, An Evaluation of Lane Closure Strategies, 1995.",
    "a " + "x" * 700,
])
def test_not_note_lines(line):
    assert not table_notes.is_note_line(line)


@pytest.mark.parametrize("line", [
    "A. Control Strategies",  # TMP strategies matrix (trans_mgmt_plans.pdf): the next section's heading
    "o Pickups & vans",  # FHWA road user cost report: a hollow bullet
    "<sup>d</sup> Applies to rural roads.",
])
def test_lettered_lines_need_their_letter_marked_in_the_table(line):
    table = "|Strategy|Auger<sup>a</sup>|**Pigments**|\n|---|---|---|\n|1|2|3|"
    assert table_notes.is_note_line(line)  # read alone, it looks like a note
    assert not table_notes.is_note_line(line, table=table)
    assert table_notes.trailing_notes(["", line, "More prose."], 0, table) == ([], 0)


def test_lettered_notes_whose_letter_the_table_marks_are_taken():
    table = "|Method|Depth|\n|---|---|\n|Auger<sup>a</sup>|3 feet|\n|Pigments**A**|20%|"
    lines = ["", "a Auger is limited to 6 inches.", "A. Use a 5% acetic acid solution.", "Prose."]
    assert table_notes.trailing_notes(lines, 0, table) == (lines[1:3], 3)


def test_a_bare_note_line_alone_is_not_taken():
    # A "Note:" with prose (not notes) after it: nothing to keep with the table.
    assert table_notes.trailing_notes(["", "Note:", "", "The signal timing is set by the engineer."], 0) == ([], 0)


# Standard Specifications p.580: pymupdf4llm's Markdown has the sideways table but not its note.
SPEC_P580 = "\n".join([
    "**Section 1080**",
    "",
    "|Acid Soluble Pigments**A**|Pigment Content|**Property**|",
    "|---|---|---|",
    "|-|20%|**Minimum**|",
    "|ASTM D1135 & D3256|ASTM D3723|**Test Method**|",
    "",
    "10-164",
])
SPEC_P580_TEXT_LAYER = [
    "Section 1080 ", " ", "10-164", "A. Use a 5% acetic acid solution with a pH 4 + 2 to determine solubility. ",
    "Acid Soluble Pigments A ", "Pigment Content ", "Property ", "Table 1080-1 ",
    "Composition of Pigments for Waterborne Paints, % By Weight ", "20% ", "Minimum ", "ASTM D1135 & D3256 ",
]


def test_a_note_the_markdown_dropped_is_recovered_under_the_table():
    notes = table_notes.missing_notes(SPEC_P580, SPEC_P580_TEXT_LAYER)

    # The caption is missing too, but it is not a note.
    assert notes == ["A. Use a 5% acetic acid solution with a pH 4 + 2 to determine solubility."]
    chunks = tables.split_text(table_notes.insert_after_last_table(SPEC_P580, notes), 512, 0, _count)
    table = next(c for c in chunks if "|---|" in c)
    # The page number after it ("10-164") is short prose that joins the last chunk, as before.
    assert "Test Method\nNotes:\nA. Use a 5% acetic acid solution with a pH 4 + 2 to determine solubility." in table


def test_notes_already_in_the_markdown_or_on_pages_without_tables_are_not_recovered():
    in_header = "|**A.** Or approved equivalent|Texanol|\n|---|---|\n|2%|5%|"
    assert table_notes.missing_notes(in_header, ["A. Or approved equivalent", "Texanol"]) == []
    assert table_notes.missing_notes("No table here.", SPEC_P580_TEXT_LAYER) == []


def test_a_note_with_a_ligature_in_the_text_layer_is_already_present():
    markdown = "|Paint|Value|\n|---|---|\n|White|20%|\n\nNote: As specified in Section 1080."
    assert table_notes.missing_notes(markdown, ["Note: As speciﬁed in Section 1080."]) == []


def test_only_table_chunks_with_a_notes_block_are_tagged():
    assert table_notes.has_notes("|A|B|\n|---|---|\n|1|2|\nNotes:\nNote: Values in feet.")
    assert not table_notes.has_notes("Notes:\nThe engineer sets the signal timing.")


def test_a_wrapped_note_takes_its_continuation_lines():
    lines = ["Note: Values apply to work zones with", "active work and lane closure.", "Pigment Content"]
    assert table_notes.missing_notes(SPEC_P580, lines) == [
        "Note: Values apply to work zones with active work and lane closure."]


def test_notes_under_a_continued_table_move_with_the_joined_table():
    # FHWA p.40-41: Table 12 runs over the page break; its "Source:" line is under the rows on p.41.
    header = "|Speed (mph)|Cars|Trucks|\n|---|---|---|"
    pages = [
        Document(text=f"Table 12. Added cost per 1,000 stops\n{header}\n|50|5.37|7.33|\n\n28",
                 metadata={"page_label": "40", "source": "fhwa.pdf"}),
        Document(text=f"Table 12. Added cost per 1,000 stops\n{header}\n|55|5.84|8.07|\n\n"
                      "Source: FHWA’s RealCost. Current year CPI: 193.396 (year 2010)\n\n"
                      "Speed change VOC is calculated by subtracting the cost factors at the work zone speed.",
                 metadata={"page_label": "41", "source": "fhwa.pdf"}),
    ]

    joined, rest = merge_continued_tables(pages)

    assert "|55|5.84|8.07|" in joined.text and "193.396" in joined.text
    assert "193.396" not in rest.text and "Speed change VOC" in rest.text
    chunk = next(c for c in tables.split_text(joined.text, 512, 0, _count) if "|---|" in c)
    assert "Trucks=8.07\nNotes:\nSource: FHWA’s RealCost. Current year CPI: 193.396 (year 2010)" in chunk
