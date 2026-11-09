"""The extraction bake-off's measures and page picking (DAR-656)."""

import json

from prototype.bakeoff import measure, report
from prototype.bakeoff.select_pages import round_robin

# TMP Design Manual p.37 as a good extractor writes it: the offset spans two rows.
GOOD = """Figure 4 - NC-PCB impact design table for ASPHALT pavement

| Offset (ft) | | Design Speed (mph) 30 | 40 |
|---|---|---|---|
| 14 | Impact Angle | 12.7 | 12.1 |
| | Maximum Deflection | 25.16 | 27.42 |
"""
# The same table as pymupdf4llm read it: the rotated header split glyph by glyph.
SCRAMBLED = """| **imp** | **act angle (degree)/** | **d** | **esign sp** | **eed(mph** |
|---|---|---|---|---|
| 14 | Impact Angle | 12.7 | 12.1 | 11.4 |
| | Maximum Deflection | 25.16 | 27.42 | 30.43 |

Figure 4 - NC-PCB impact design table for ASPHALT pavement
"""
HTML = "<table><tr><td>Offset (ft)</td><td>40</td></tr><tr><td>14</td><td>27.42</td></tr></table>"


def test_cell_found_needs_the_value_next_to_its_row_label():
    assert measure.cell_found(GOOD, "27.42", "14")
    assert measure.cell_found(SCRAMBLED, "27.42", "14")
    assert measure.cell_found(HTML, "27.42", "14")
    assert not measure.cell_found(GOOD, "25.16", "20")
    # "14" must be a whole token: not the end of 12.14, not 127.42 for 27.42.
    assert not measure.cell_found("| 20 | 12.14 | 27.42 |", "27.42", "14")
    assert not measure.cell_found("| 14 | 127.42 |", "27.42", "14")


def test_header_cells_must_appear_verbatim():
    assert measure.cell_found(GOOD, "Offset (ft)")
    assert measure.cell_found(HTML, "Offset (ft)")
    assert not measure.cell_found(SCRAMBLED, "Offset (ft)")


def test_normalize_drops_markdown_emphasis_and_odd_dashes():
    assert measure.normalize("**Maximum** **Deflection** W1‑6") == "maximum deflection w1-6"


def test_header_fragmentation_flags_glyph_split_headers():
    scrambled = measure.tables(SCRAMBLED)[0]["header"]
    clean = measure.tables(GOOD)[0]["header"]
    assert measure.header_fragmentation(scrambled) > measure.header_fragmentation(clean)


def test_tables_reads_pipe_and_html_blocks():
    assert [t["rows"] for t in measure.tables(GOOD)] == [3]
    assert measure.tables(HTML)[0]["header"] == ["offset (ft)", "40"]
    assert measure.tables("no table here") == []


def test_caption_attached_looks_a_few_lines_around_the_table():
    assert measure.caption_attached(GOOD) is True
    assert measure.caption_attached(SCRAMBLED) is True
    far = GOOD.replace("Figure 4", "Figure 4\n\nx\n\ny\n\nz\n\nw")
    assert measure.caption_attached(far) is False
    assert measure.caption_attached("text only") is None
    assert measure.captions(GOOD) == ["figure 4"]


def test_numbers_and_units_are_multisets():
    assert measure.numbers("1,500 ft and 1500 ft, 12.5%")["1500"] == 2
    units = measure.units("12' wide, 6\" deep, 45 mph, 10 feet")
    assert units["ft"] == 2 and units["in"] == 1 and units["mph"] == 1


def test_round_robin_spreads_a_kind_over_documents():
    ranked = [(-1.0, ("a.pdf", 1)), (-0.9, ("a.pdf", 2)), (-0.8, ("a.pdf", 3)), (-0.5, ("b.pdf", 7))]
    assert round_robin(ranked, 3, taken=set()) == [("a.pdf", 1), ("b.pdf", 7), ("a.pdf", 2)]
    assert round_robin(ranked, 2, taken={("a.pdf", 1)}) == [("a.pdf", 2), ("b.pdf", 7)]


def test_report_scores_a_candidate_against_the_text_layer(tmp_path):
    pages = [{"id": "wztc/t.pdf#37", "kind": "spanned_header", "audit": {"nt": 1}},
             {"id": "wztc/s.pdf#4", "kind": "scan", "audit": {"nt": 0}}]
    reference = {"wztc/t.pdf#37": {"text": GOOD}, "wztc/s.pdf#4": {"text": ""}}
    rows = {"wztc/t.pdf#37": {"id": "wztc/t.pdf#37", "text": SCRAMBLED, "seconds": 2.0, "error": None},
            "wztc/s.pdf#4": {"id": "wztc/s.pdf#4", "text": "Use W8-11 signs " * 10, "seconds": 4.0, "error": None}}
    cells = [{"id": "wztc/t.pdf#37", "value": "Offset (ft)", "row_label": None},
             {"id": "wztc/t.pdf#37", "value": "27.42", "row_label": "14"},
             {"id": "wztc/s.pdf#4", "value": "W8-11", "row_label": None}]
    result = report.score_candidate("x", rows, reference, pages, cells)
    assert result["cells_ok"] == "2/3"
    assert result["offset_ft_verbatim"] == "0/1"
    assert result["no_text_read"] == "1/1"
    assert result["table_pages_found"] == "1/1"
    assert result["seconds_mean"] == 3.0

    doc = tmp_path / "doc.md"
    doc.write_text(f"# Title\n\nprose\n\n{report.START}\nold\n{report.END}\n\nmore prose\n", encoding="utf-8")
    report.write_doc(doc, "new table")
    text = doc.read_text(encoding="utf-8")
    assert "new table" in text and "old" not in text and text.endswith("more prose\n")


def test_committed_cells_point_at_selected_pages():
    from pathlib import Path

    here = Path(report.__file__).resolve().parent
    pages = {p["id"] for p in json.loads((here / "pages.json").read_text(encoding="utf-8"))}
    cells = json.loads((here / "cells.json").read_text(encoding="utf-8"))["cells"]
    assert len(cells) == 30
    assert all(c["id"] in pages for c in cells)


def test_inlined_images_do_not_count_as_numbers():
    text = "See ![Figure 2](data:image/jpeg;base64,/9j/4AAQ1234567) at 45 mph"
    assert measure.strip_images(text) == "See Figure 2 at 45 mph"
    assert sum(measure.numbers(measure.strip_images(text)).values()) == 2


def test_review_cases_for_html_and_shifted_rows():
    # A caption under an HTML table (MinerU) counts as attached.
    assert measure.caption_attached("<table><tr><td>14</td><td>27.42</td></tr></table>\n\nFigure 4 - x") is True
    # colspan/rowspan attributes are not numbers or inch marks.
    assert measure.numbers('<td colspan="2">14</td>') == measure.numbers("14")
    assert not measure.units('<td colspan="2">14</td>')
    # A value shifted into the next labelled row is not read right.
    assert not measure.cell_found("| 14 | 1.0 |\n| 20 | 27.42 |", "27.42", "14")
    # ...but a value in the row under a row-spanned label is.
    rowspan = ("<table><tr><td rowspan=2>14</td><td>Impact Angle</td><td>12.1</td></tr>"
               "<tr><td>Maximum Deflection</td><td>27.42</td></tr></table>")
    assert measure.cell_found(rowspan, "27.42", "14")


def test_near_duplicate_pairs_stay_whole():
    from prototype.bakeoff.select_pages import round_robin_pairs

    pairs = [(-0.9, (("a", 1), ("a", 2))), (-0.8, (("a", 5), ("a", 6))),
             (-0.7, (("b", 1), ("b", 2))), (-0.6, (("c", 1), ("c", 2)))]
    picked = round_robin_pairs(pairs, 5, taken={("a", 1)})
    assert picked == [("a", 5), ("a", 6), ("b", 1), ("b", 2), ("c", 1), ("c", 2)]


def test_empty_first_pipe_cell_continues_the_spanned_row():
    # pymupdf4llm writes the cell under a row-spanned offset as "||".
    assert measure.cell_found("|20|impact angle|12.2|11.5|\n||maximum deflection|23.61|25.37|", "25.37", "20")
