"""Tests for joining tables that continue across PDF pages (rag/table_merge.py, DAR-655)."""

import pytest
from llama_index.core import Document

from rag import loader
from rag.table_merge import merge_continued_tables, merge_decisions, page_lines, page_span

HEADER = "|Offset (ft)|Design speed|Impact angle|Max deflection (ft)|\n|---|---|---|---|"


def _page(n, text, source="tmp.pdf", **metadata):
    return Document(text=text, metadata={"page_label": str(n), "source": source, **metadata})


def _rows(text):
    return [line for line in text.split("\n") if line.startswith("|") and not set(line) <= set("|-: ")]


def test_a_table_whose_header_repeats_on_the_next_page_becomes_one_table():
    pages = [
        _page(1, f"## 6.2 Barrier deflection\n\nTable 6-1 Maximum deflection\n{HEADER}\n|14|40 mph|12.1|27.42|\n|20|40 mph|12.1|31.10|\n\n37"),
        _page(2, f"38\n\n{HEADER}\n|26|40 mph|12.1|34.80|\n|32|40 mph|12.1|36.95|"),
    ]

    merged = merge_continued_tables(pages)

    (doc,) = merged
    assert doc.metadata["page_label"] == "1" and doc.metadata["page_end"] == 2
    rows = _rows(doc.text)
    assert rows[0].startswith("|Offset (ft)|") and sum(r.startswith("|Offset") for r in rows) == 1  # repeat dropped
    assert [r.split("|")[1] for r in rows[1:]] == ["14", "20", "26", "32"]
    assert merge_decisions(pages)[0].reason == "header"


def test_a_table_over_three_pages_chains_and_the_prose_after_it_keeps_its_page():
    pages = [
        _page(1, f"Table 2-1 Lane closure lengths\n{HEADER}\n|1|45 mph|5|10|"),
        _page(2, f"Table 2-1 (continued)\n|2|50 mph|6|11|\n|---|---|---|---|\n|3|55 mph|7|12|"),
        _page(3, "Table 2-1 (continued)\n|4|60 mph|8|13|\n|---|---|---|---|\n|5|65 mph|9|14|\n\n## 2.5 Flaggers\n\nFlaggers shall wear class 3 apparel."),
    ]

    merged = merge_continued_tables(pages)

    assert [(d.metadata["page_label"], d.metadata.get("page_end")) for d in merged] == [("1", 3), ("3", None)]
    assert [r.split("|")[1] for r in _rows(merged[0].text)[1:]] == ["1", "2", "3", "4", "5"]
    assert "Flaggers shall wear" in merged[1].text and "|" not in merged[1].text
    assert [d.reason for d in merge_decisions(pages)] == ["continued", "continued"]


def test_a_page_that_is_all_table_and_footer_lets_the_table_run_on():
    # The Legal Guide: every page is one table under "NCDOT Traffic Services Legal Guide (revised 6/20/23)".
    footer = "NCDOT Traffic Services Legal Guide (revised 6/20/23)\n\nPage {} of 706"
    box = {"table_bboxes": [[0.05, 0.08, 0.95, 0.93]]}
    pages = [_page(n, f"|{n}a|x|y|z|\n|---|---|---|---|\n|{n}b|x|y|z|\n\n" + footer.format(n), **box) for n in (17, 18, 19)]

    merged = merge_continued_tables(pages)

    assert [(d.metadata["page_label"], d.metadata.get("page_end")) for d in merged] == [("17", 19)]
    assert [r.split("|")[1] for r in _rows(merged[0].text)] == ["17a", "17b", "18a", "18b", "19a", "19b"]
    assert [(d.page, d.next_page, d.merged) for d in merge_decisions(pages)] == [(17, 18, True), (18, 19, True)]


def test_tables_with_different_column_counts_stay_apart_even_with_a_continued_caption():
    pages = [
        _page(1, f"Table 6-1 Maximum deflection\n{HEADER}\n|14|40 mph|12.1|27.42|"),
        _page(2, "Table 6-2 (continued)\n|Sign|Size|\n|---|---|\n|W20-1|48 in|"),
    ]

    merged = merge_continued_tables(pages)
    (decision,) = merge_decisions(pages)

    assert [d.metadata["page_label"] for d in merged] == ["1", "2"]
    assert not decision.merged and decision.reason == "column count 4 vs 2"


def test_no_signal_or_prose_between_the_tables_keeps_them_apart():
    other = "|Sign|Size|Color|Use|\n|---|---|---|---|\n|W20-1|48 in|orange|ahead|"
    no_signal = [_page(1, f"{HEADER}\n|14|40 mph|12.1|27.42|"), _page(2, other)]
    prose = [_page(1, f"{HEADER}\n|14|40 mph|12.1|27.42|"),
             _page(2, "The deflection values above assume a level shoulder and no curb in front of the barrier.\n" + HEADER + "\n|20|40 mph|12.1|31.10|")]

    assert len(merge_continued_tables(no_signal)) == 2
    assert merge_decisions(no_signal)[0].reason.startswith("no merge signal")
    assert len(merge_continued_tables(prose)) == 2
    assert merge_decisions(prose)[0].reason == "next page starts with prose"


def test_boxes_at_the_page_edges_merge_and_are_not_kept_on_the_result():
    other_header = "|15|35 mph|11.0|25.00|\n|---|---|---|---|"
    pages = [
        _page(1, f"{HEADER}\n|14|40 mph|12.1|27.42|", table_bboxes=[[0.1, 0.5, 0.9, 0.95]]),
        _page(2, f"{other_header}\n|20|40 mph|12.1|31.10|", table_bboxes=[[0.1, 0.05, 0.9, 0.3]]),
    ]
    apart = [_page(1, pages[0].text, table_bboxes=[[0.1, 0.2, 0.9, 0.6]]), _page(2, pages[1].text, table_bboxes=[[0.1, 0.05, 0.9, 0.3]])]

    (doc,) = merge_continued_tables(pages)

    assert doc.metadata["page_end"] == 2 and "table_bboxes" not in doc.metadata
    assert [r.split("|")[1] for r in _rows(doc.text)[1:]] == ["14", "15", "20"]  # page 2's "header" was a data row
    assert len(merge_continued_tables(apart)) == 2


def test_a_continuation_missing_its_empty_last_column_is_padded_back():
    # The Legal Guide's "TEPPL Topic" column is empty on some pages, and pymupdf4llm drops it there.
    pages = [
        _page(1, "|Statute|Topic|TEPPL Topic|\n|---|---|---|\n|20-171|Speed|S-12|"),
        _page(2, "Table 1 (continued)\n|136-63|Signs|\n|---|---|\n|1993-0533|Parking|"),
    ]

    (doc,) = merge_continued_tables(pages)

    assert _rows(doc.text)[-2:] == ["|136-63|Signs||", "|1993-0533|Parking||"]


def test_a_narrower_table_at_the_top_of_the_next_page_needs_a_continued_caption():
    pages = [
        _page(1, f"{HEADER}\n|14|40 mph|12.1|27.42|", table_bboxes=[[0.1, 0.5, 0.9, 0.95]]),
        _page(2, "|Sign|Size|Use|\n|---|---|---|\n|W20-1|48 in|ahead|", table_bboxes=[[0.1, 0.05, 0.9, 0.3]]),
    ]

    assert len(merge_continued_tables(pages)) == 2
    assert merge_decisions(pages)[0].reason == "column count 4 vs 3 without a continued caption"


def test_the_lowest_box_on_the_page_is_the_one_that_runs_off_it():
    # A small side table starts lower than the tall table but ends higher.
    pages = [
        _page(1, f"{HEADER}\n|14|40 mph|12.1|27.42|", table_bboxes=[[0.1, 0.1, 0.6, 0.97], [0.65, 0.8, 0.9, 0.88]]),
        _page(2, "|15|35 mph|11.0|25.00|\n|---|---|---|---|\n|20|40 mph|12.1|31.10|", table_bboxes=[[0.1, 0.05, 0.9, 0.3]]),
    ]

    assert merge_decisions(pages)[0].reason == "geometry"


def test_a_heading_above_the_continuation_is_kept_with_the_rest_of_the_page():
    pages = [
        _page(1, f"Table 6-1 Maximum deflection\n{HEADER}\n|14|40 mph|12.1|27.42|"),
        _page(2, f"## 6.3 Curbs\n\nTable 6-1 (continued)\n|20|40 mph|12.1|31.10|\n|---|---|---|---|\n\nCurbs in front of barrier are not allowed."),
    ]

    merged = merge_continued_tables(pages)

    assert [(d.metadata["page_label"], d.metadata.get("page_end")) for d in merged] == [("1", 2), ("2", None)]
    assert merged[1].text.startswith("## 6.3 Curbs") and "(continued)" not in merged[1].text
    assert "Curbs in front" in merged[1].text


def test_a_chunk_of_a_joined_table_cites_the_pages_its_rows_came_from():
    loaded = [
        _page(1, f"Prose on page one.\n\n|Sign|Size|\n|---|---|\n|W20-1|48 in|\n\nMore prose.\n\n{HEADER}\n|14|40 mph|12.1|27.42|"),
        _page(2, f"{HEADER}\n|20|40 mph|12.1|31.10|\n|26|40 mph|12.1|34.80|"),
        _page(3, f"{HEADER}\n|32|40 mph|12.1|36.95|\n\n37"),
    ]
    lines = page_lines(loaded)

    # A later part of the split table repeats page 1's header; its rows are on pages 2 and 3.
    assert page_span(f"{HEADER}\n|26|40 mph|12.1|34.80|\n|32|40 mph|12.1|36.95|", lines, 1, 3) == (2, 3)
    assert page_span(f"{HEADER}\n|32|40 mph|12.1|36.95|", lines, 1, 3) == (3, None)
    assert page_span(f"More prose.\n\n{HEADER}\n|32|40 mph|12.1|36.95|", lines, 1, 3) == (3, None)  # caption repeated from p.1
    # The page's other table and prose stay on page 1 alone.
    assert page_span("Prose on page one.\n\n|Sign|Size|\n|---|---|\n|W20-1|48 in|", lines, 1, 3) == (1, None)
    assert page_span(f"{HEADER}\n|14|40 mph|12.1|27.42|\n|20|40 mph|12.1|31.10|", lines, 1, 3) == (1, 2)


def test_pages_of_different_documents_or_not_adjacent_are_never_joined():
    first = _page(1, f"{HEADER}\n|14|40 mph|12.1|27.42|")
    assert len(merge_continued_tables([first, _page(2, f"{HEADER}\n|20|40 mph|12.1|31.10|", source="other.pdf")])) == 2
    assert len(merge_continued_tables([first, _page(3, f"{HEADER}\n|20|40 mph|12.1|31.10|")])) == 2


def test_a_ruled_table_running_off_a_pdf_page_is_one_table_after_loading(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    left, col_w, row_h = 72, 110, 20

    def table(page, top, rows):
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                rect = pymupdf.Rect(left + c * col_w, top + r * row_h, left + (c + 1) * col_w, top + (r + 1) * row_h)
                page.draw_rect(rect, color=(0, 0, 0), width=0.8)
                page.insert_text((rect.x0 + 4, rect.y1 - 6), cell, fontsize=10)

    first = pdf.new_page()  # A4, 595 x 842: rows from y=100 to y=800, in the bottom 10%
    first.insert_text((72, 80), "Table 4-1 Taper lengths", fontsize=12)
    table(first, 100, [["Speed (mph)", "Lane width (ft)", "Taper (ft)"]] + [[str(20 + i), "12", str(100 + i)] for i in range(34)])
    second = pdf.new_page()  # continues at y=50, inside the top 12%, without repeating the header
    table(second, 50, [[str(54 + i), "12", str(134 + i)] for i in range(5)])
    second.insert_text((72, 200), "Longer tapers apply on curves.", fontsize=11)
    pdf.save(tmp_path / "manual.pdf")

    pages = loader.load(tmp_path, tables=True)
    merged = merge_continued_tables(pages)

    assert pages[0].metadata["table_bboxes"] and pages[1].metadata["table_bboxes"]
    assert merged[0].metadata["page_end"] == 2
    rows = _rows(merged[0].text)
    assert rows[0].startswith("|Speed (mph)|") and rows[-1].startswith("|58|")
    assert len(rows) == 1 + 34 + 5
    assert merged[1].metadata["page_label"] == "2" and "Longer tapers" in merged[1].text


def test_continued_markers_are_told_from_prose_that_says_continued():
    from rag.table_merge import _is_continued_caption

    assert _is_continued_caption("Initial List of Candidate Locations - continued")
    assert _is_continued_caption("**Table 2C-1. Warning Sign and Plaque Sizes (Sheet 4 of 4)**")
    assert _is_continued_caption("(Continued)")
    assert not _is_continued_caption("Lane closures continued per the schedule in Section 6.")
    assert not _is_continued_caption("Table 2C-1. Warning Sign and Plaque Sizes (Sheet 1 of 4)")
