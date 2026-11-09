"""OCR orientation retry, confidence flags and figure chunks (DAR-658)."""

import importlib.util

import numpy as np
import pymupdf
import pytest

from rag import figures, ocr


def _reader_upright_at(original: np.ndarray, turns: int, calls: list):
    """A fake OCR engine that reads well only when the image has been turned `turns` quarter turns."""
    upright = np.rot90(original, turns)

    def read(img):
        calls.append(img.shape)
        if img.shape == upright.shape and np.array_equal(img, upright):
            return [([[0, 0], [90, 0], [90, 10], [0, 10]], "L1 = N + 0.75 + LANE WIDTH", 0.97)]
        return [([[0, 0], [10, 0], [10, 10], [0, 10]], "H RO", 0.6)]

    return read


def test_a_sideways_page_is_read_in_the_orientation_with_the_most_confident_text():
    image = np.arange(24, dtype=np.uint8).reshape(4, 6)
    calls = []
    best, tried = ocr.read_oriented(image, _reader_upright_at(image, 3, calls), first=0)
    assert best.turns == 3 and best.degrees == 270
    assert best.lines[0][1].startswith("L1 = N")
    assert tried == [0, 90, 180, 270]


def test_a_confident_first_reading_is_not_retried():
    image = np.arange(24, dtype=np.uint8).reshape(4, 6)
    calls = []
    best, tried = ocr.read_oriented(image, _reader_upright_at(image, 1, calls), first=1)
    assert best.turns == 1 and tried == [90] and len(calls) == 1


def test_low_confidence_and_turned_pages_are_flagged():
    assert ocr.PageOcr(0, 0, 0.62, [0], ["H RO"]).flags == ["ocr_low_conf"]
    assert ocr.PageOcr(0, 270, 0.96, [0, 270], ["DETAIL 2B"]).flags == ["rotated"]
    assert ocr.PageOcr(0, 0, 0.0, [0], []).flags == []


def test_ocr_lines_are_grouped_into_rows_left_to_right():
    lines = [
        ([[200, 0], [260, 0], [260, 10], [200, 10]], "0.75", 0.9),
        ([[0, 1], [100, 1], [100, 11], [0, 11]], "L1 = N +", 0.9),
        ([[0, 30], [80, 30], [80, 40], [0, 40]], "DETAIL 2B", 0.9),
    ]
    assert ocr.rows(lines) == ["L1 = N +  0.75", "DETAIL 2B"]


def _page_with_text(rotate: int, page_rotation: int = 0):
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((150, 150), "WARRANT POINT", fontsize=12, rotate=rotate)
    page.set_rotation(page_rotation)
    return doc, page


@pytest.mark.parametrize("rotate, page_rotation, turns", [(0, 0, 0), (90, 0, 3), (270, 0, 1), (0, 90, 1), (90, 90, 0)])
def test_the_orientation_hint_follows_line_direction_and_page_rotation(rotate, page_rotation, turns):
    _doc, page = _page_with_text(rotate, page_rotation)
    assert ocr.orientation_hint(page) == turns


def test_rows_not_written_onto_the_page_are_appended_under_a_header():
    reader = ocr.OrientedOcr(read=lambda img: [])
    reader.pages[3] = ocr.PageOcr(3, 270, 0.96, [0, 270], ["DETAIL 2B", "L1 = N + 0.75"], ["DETAIL 2B", "L1 = N + 0.75"])
    reader.pages[4] = ocr.PageOcr(4, 0, 0.99, [0], ["MEMO TO"])
    reader.pages[6] = ocr.PageOcr(6, 0, 0.95, [0], ["SHOULDER", "CLOSED AHEAD"], ["CLOSED AHEAD"])
    assert reader.appended_text(3) == "OCR text (page turned 270 degrees):\nDETAIL 2B\nL1 = N + 0.75"
    assert reader.appended_text(6) == "OCR text (sideways labels):\nCLOSED AHEAD"
    assert reader.appended_text(4) == "" and reader.appended_text(5) == ""


def test_sideways_lines_count_for_nothing_when_readings_are_compared():
    tall = ([[0, 0], [10, 0], [10, 200], [0, 200]], "LENGTH OF NEED 350 FEET", 0.99)
    level = ([[0, 0], [200, 0], [200, 10], [0, 10]], "LENGTH OF NEED", 0.9)
    assert ocr.sideways(tall) and not ocr.sideways(level)
    assert ocr.Reading(0, [tall]).weight == 0 and ocr.Reading(0, [tall]).sideways_share == 1.0
    assert ocr.Reading(1, [level]).weight > 0


@pytest.mark.skipif(importlib.util.find_spec("rapidocr") is None, reason="needs rapidocr")
def test_a_scanned_page_of_sideways_text_is_read_turned_upright(tmp_path):
    # A page of text laid out sideways (rotate=90 reads bottom to top), rendered
    # to an image and saved as an image-only PDF, as a scanned drawing would be.
    source = pymupdf.open()
    page = source.new_page(width=612, height=792)
    for i, line in enumerate(["GUARDRAIL PLACEMENT ON TRAILING END", "OF RIGID OBSTACLE WARRANT",
                              "LENGTH OF NEED 350 FEET", "DESIGN SPEED 60 MPH"]):
        page.insert_text((150 + 60 * i, 650), line, fontsize=22, rotate=90)
    pix = page.get_pixmap(dpi=150)
    scan = pymupdf.open()
    scan_page = scan.new_page(width=612, height=792)
    scan_page.insert_image(scan_page.rect, pixmap=pix)
    path = tmp_path / "scan.pdf"
    scan.save(path)

    from rag.loader import _PdfMarkdownReader

    (document,) = _PdfMarkdownReader(ocr=True).load_data(path)
    text = document.text.upper()
    assert "OCR text (page turned" in document.text
    assert "LENGTH OF NEED" in text and "350" in text
    assert document.metadata["ocr_degrees"] in (90, 270)
    assert "rotated" in document.metadata["flags"]


def test_a_drawing_caption_gets_a_figure_chunk_with_nearby_lines_and_ocr_labels():
    page = "\n".join([
        "ROADWAY DESIGN MANUAL", "PART 1", "", "**DETAIL 2B**", "END OF GUARDRAIL", "WARRANT POINT",
        "", "OCR text (page turned 270 degrees):", "ON TRAILING END OF RIGID OBSTACLE WARRANT",
        "L1 = N + 0.75 + LANE WIDTH", "WARRANT POINT",
    ])
    assert figures.figure_captions(page) == ["DETAIL 2B"]
    ((caption, text),) = figures.figure_chunks(page)
    assert caption == "DETAIL 2B"
    lines = text.splitlines()
    assert lines[:3] == ["DETAIL 2B", "ROADWAY DESIGN MANUAL", "PART 1"]
    assert "L1 = N + 0.75 + LANE WIDTH" in lines
    assert lines.count("WARRANT POINT") == 1  # a label already among the nearby lines isn't repeated


def test_prose_mentioning_a_figure_and_table_captions_get_no_figure_chunk():
    page = ("Figure 3 shows the merging taper for each speed, with the lengths in the table that follows and "
            "a note on lane widths, shoulders and the buffer space that applies to every case in this section.\n"
            "Table 6H-3 Taper lengths\n| a | b |")
    assert figures.figure_chunks(page) == []


def test_figure_chunks_stay_within_the_embedders_window():
    page = "Figure 5 - Sign layout\n" + "OCR text (page turned 90 degrees):\n" + "\n".join(f"LABEL {i} 12 FT" for i in range(400))
    ((_, text),) = figures.figure_chunks(page)
    assert len(text) <= figures.MAX_FIGURE_CHARS


def test_the_no_text_report_lists_image_only_and_text_loss_pages_with_their_status():
    from prototype.no_text_pages import markdown, report

    def page(i, chars, imgs=0, blank=False):
        return {"i": i, "chars": chars, "imgs": imgs, "blank": blank, "rotchars": 0}

    audit = {"tmsd/scan.pdf": {"pages": [page(1, 0, 1), page(2, 0, 1), page(3, 0, 1, blank=True), page(4, 900)]},
             "wztc/other.pdf": {"pages": [page(1, 0, 1)]}}

    def chunk(division, source, p, text, **extra):
        return {"division": division, "source": source, "page": p, "text": text, **extra}

    baseline = [chunk("tmsd", "scan.pdf", 4, "x" * 100), chunk("tmsd", "scan.pdf", 5, "kept")]
    new = [chunk("tmsd", "scan.pdf", 1, "MEMO TO: Debbie Barbour, Director", flags=["rotated"]),
           chunk("tmsd", "scan.pdf", 2, "Figure 1 - a long figure caption here", kind="figure"),
           chunk("tmsd", "scan.pdf", 4, "y" * 600)]

    result = report(audit, baseline, [new])

    status = {(r["source"], r["page"]): (r["status"], r["flags"]) for r in result["image_only"] + result["text_loss"]}
    assert status == {("scan.pdf", 1): ("fixed", ["rotated"]), ("scan.pdf", 2): ("not fixed", []),
                      ("scan.pdf", 4): ("fixed", []), ("other.pdf", 1): ("not rebuilt", [])}
    assert result["lost"] == [{"division": "tmsd", "source": "scan.pdf", "page": 5}]
    assert "## Image-only pages (3: 1 fixed, 1 not fixed, 1 not rebuilt)" in markdown(result, ["index-U16"])


def test_short_captions_count_and_prose_naming_a_figure_does_not():
    assert figures.figure_captions("Figure 5\nDETAIL A\nExhibit 3 shows the required taper lengths.") == ["Figure 5", "DETAIL A"]


def test_pages_inside_a_table_joined_over_a_page_break_keep_their_text():
    # TMP Design Manual pp. 5-7: one joined table chunk from p. 5 was reported as pp. 6-7 losing all their text.
    from prototype.no_text_pages import page_text

    chunks = [{"division": "wztc", "source": "tmp.pdf", "page": 5, "page_end": 7, "text": "x" * 300},
              {"division": "wztc", "source": "tmp.pdf", "page": 9, "text": "caption", "kind": "figure"}]
    text = page_text(chunks)
    assert [text[("wztc", "tmp.pdf", p)] for p in (5, 6, 7)] == [100, 100, 100]
    assert ("wztc", "tmp.pdf", 9) not in text
