"""Tests for rag.pages: the number a PDF page prints, next to its index in the file (DAR-654)."""

import pytest

from rag import pages

pymupdf = pytest.importorskip("pymupdf")


def _pdf(path, footers=(), headers=(), labels=None, rotation=0):
    """A PDF with one page per footer (and header) text; `labels` is a pymupdf page-label spec."""
    pdf = pymupdf.open()
    count = max(len(footers), len(headers))
    for i in range(count):
        page = pdf.new_page(width=612, height=792)
        page.set_rotation(rotation)
        height = page.rect.height  # as displayed

        def put(x, y, text, size):
            # Placed where it shows on the displayed page, upright, as on the corpus's landscape sheets.
            page.insert_text(pymupdf.Point(x, y) * page.derotation_matrix, text, fontsize=size, rotate=rotation)

        put(72, height / 2, f"Body text of page {i + 1} about work zones.", 11)
        if i < len(headers) and headers[i]:
            put(72, 0.05 * height, headers[i], 9)  # top 5% of the page
        if i < len(footers) and footers[i]:
            put(400, 0.96 * height, footers[i], 9)  # bottom 4% of the page
    if labels:
        pdf.set_page_labels(labels)
    pdf.save(path)
    return path


# -- labels -------------------------------------------------------------------------------------------------------------

def test_undecoded_utf16_labels_are_decoded_and_blank_ones_are_none():
    assert pages.decode_label("<FEFF0041>1") == "A1"  # the STEP guide's cover pages, as PyMuPDF returns them
    assert pages.decode_label("<0041>3") == "A3"
    assert pages.decode_label(" iv ") == "iv"
    assert pages.decode_label("") is None
    assert pages.decode_label(None) is None


def test_labels_with_a_roman_prefix_and_a_lettered_prefix_are_preferred_over_the_footer(tmp_path):
    # Front matter i-iii, then 1-3, as a viewer shows them; footers print the same numbers.
    labels = [{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
              {"startpage": 3, "prefix": "", "style": "D", "firstpagenum": 1}]
    path = _pdf(tmp_path / "manual.pdf", footers=["i", "ii", "iii", "1", "2", "3"], labels=labels)

    identities = pages.document_identities(path)

    assert [i.pdf_label for i in identities] == ["i", "ii", "iii", "1", "2", "3"]
    assert [(i.printed, i.source) for i in identities] == [(x, "label") for x in ["i", "ii", "iii", "1", "2", "3"]]
    assert [i.pdf_index for i in identities] == [1, 2, 3, 4, 5, 6]


def test_a_prefixed_label_set_on_the_cover_pages_reads_as_a1_a2(tmp_path):
    labels = [{"startpage": 0, "prefix": "A", "style": "D", "firstpagenum": 1},
              {"startpage": 2, "prefix": "", "style": "D", "firstpagenum": 1}]
    path = _pdf(tmp_path / "step.pdf", footers=["", "", "1", "2", "3"], labels=labels)

    identities = pages.document_identities(path)

    assert [i.printed for i in identities] == ["A1", "A2", "1", "2", "3"]
    assert {i.source for i in identities} == {"label"}


# -- footers and headers ------------------------------------------------------------------------------------------------

def test_page_n_footers_give_the_printed_number_and_chapter_restarts_are_allowed(tmp_path):
    # The TMP Design Manual: "Part 2: Chapter 5 | July 2019| Page 13" on PDF p.37, restarting at each chapter.
    footers = ["", "Part 2: Chapter 4 | July 2019 | Page 11", "Part 2: Chapter 4 | July 2019 | Page 12",
               "Part 2: Chapter 5 | July 2019| Page 1", "Part 2: Chapter 5 | July 2019| Page 2"]
    path = _pdf(tmp_path / "tmp.pdf", footers=footers)

    identities = pages.document_identities(path)

    assert [i.printed for i in identities] == [None, "11", "12", "1", "2"]
    assert identities[1].source == "footer" and identities[1].pdf_label is None
    assert pages.page_identity(path, 3).printed == "1"


def test_chapter_and_appendix_pages_keep_the_whole_string(tmp_path):
    # The UAM's "July 2022  2-48" footers and "D-1" appendix pages: "5-13" must never become "13".
    footers = ["July 2022 2-47", "July 2022 2-48", "July 2022 3-1", "July 2022 3-2", "July 2022 D-1", "July 2022 D-2"]
    path = _pdf(tmp_path / "uam.pdf", footers=footers)

    assert [i.printed for i in pages.document_identities(path)] == ["2-47", "2-48", "3-1", "3-2", "D-1", "D-2"]


def test_roman_front_matter_then_bare_integers(tmp_path):
    path = _pdf(tmp_path / "guide.pdf", footers=["", "ii", "iii", "iv", "1", "2", "3"])

    assert [i.printed for i in pages.document_identities(path)] == [None, "ii", "iii", "iv", "1", "2", "3"]


def test_a_number_only_in_the_header_is_used_when_the_footer_has_none(tmp_path):
    headers = ["383 Federal Highway Administration, DOT", "384 23 CFR Ch. I (4-1-24 Edition)",
               "385 Federal Highway Administration, DOT"]
    path = _pdf(tmp_path / "cfr.pdf", headers=headers, footers=["Jkt 262082", "Jkt 262082", "Jkt 262082"])

    identities = pages.document_identities(path)

    assert [(i.printed, i.source) for i in identities] == [("383", "header"), ("384", "header"), ("385", "header")]


def test_a_sign_code_in_every_footer_is_rejected(tmp_path):
    # "W1-1" is a warning-sign code on the Roadway Standard Drawings, the same on every sheet.
    path = _pdf(tmp_path / "rsd.pdf", footers=["W1-1 48\"X48\"", "W1-1 48\"X48\"", "W1-1 48\"X48\"", "W1-1 48\"X48\""])

    assert [i.printed for i in pages.document_identities(path)] == [None] * 4


def test_a_publication_number_and_a_single_page_one_are_rejected(tmp_path):
    # "FHWA-HRT-04-091" on a cover, "Technical Report Documentation Page 1." once: no run of page numbers.
    path = _pdf(tmp_path / "report.pdf", footers=["Publication No. FHWA-HRT-04-091", "Documentation Page 1", "", ""])

    assert [i.printed for i in pages.document_identities(path)] == [None] * 4


def test_sheet_numbers_that_restart_every_standard_are_rejected(tmp_path):
    # Title blocks of the Roadway Standard Drawings: sheet 1, 2, 3 of each standard.
    path = _pdf(tmp_path / "sheets.pdf", footers=["1", "2", "3", "1", "2", "3", "1", "2", "3"])

    assert [i.printed for i in pages.document_identities(path)] == [None] * 9


def test_the_line_nearest_the_edge_wins_over_a_contents_line_above_it(tmp_path):
    # The UAM contents page lists "2.8.2 Temporary Shoring ..... 2-48" just above its own footer "ii".
    pdf = pymupdf.open()
    for n, numeral in enumerate(["i", "ii", "iii"], 1):
        page = pdf.new_page(width=612, height=792)
        page.insert_text((72, 300), f"Contents page {n}", fontsize=11)
        page.insert_text((72, 735), f"2.8.{n} Temporary Shoring ........... 2-4{n + 6}", fontsize=9)
        page.insert_text((300, 760), numeral, fontsize=9)
    path = tmp_path / "contents.pdf"
    pdf.save(path)

    assert [i.printed for i in pages.document_identities(path)] == ["i", "ii", "iii"]


def test_rotated_pages_use_the_displayed_top_and_bottom(tmp_path):
    path = _pdf(tmp_path / "landscape.pdf", footers=["Page 5", "Page 6", "Page 7"], rotation=90)

    assert [i.printed for i in pages.document_identities(path)] == ["5", "6", "7"]


def test_a_document_opened_in_memory_is_read_without_the_cache(tmp_path):
    path = _pdf(tmp_path / "memo.pdf", footers=["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"])
    with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as doc:
        assert pages.page_identity(doc, 1).printed == "2"
    with pymupdf.open(path) as doc:
        assert pages.page_identity(doc, 2) == pages.PageIdentity(3, None, "3", "footer")


# -- the regex families, on header and footer lines copied from the corpus audit ---------------------------------------

@pytest.mark.parametrize("line, family, number", [
    ("Part 2: Chapter 5 | July 2019| Page 13", "page", "13"),  # TMP Design Manual, PDF p.37
    ("NCDOT Traffic Services Legal Guide (revised 6/20/23) | Page 228 of 706", "page", "228"),  # L18_TSLG_Guide
    ("MUTCD 11th Edition | Page 619", "page", "619"),  # part3.pdf
    ("initial green period. The Maximum Initial can not be less than the Minimum Green (Figure 5-6). | 5-24", "chapter", "5-24"),  # noqa: E501  fhwa_hop_08_024, foot
    ("July 2022 | D-1", "appendix", "D-1"),  # UAM appendix
    ("DEVELOPING AND IMPLEMENTING TRANSPORTATION MANAGEMENT PLANS FOR WORK ZONES | Appendix B-1", "appendix", "B-1"),  # noqa: E501  trans_mgmt_plans
    ("B-77 | § 645.105 Definitions.", "appendix", "B-77"),  # if03014.pdf, head
    ("iii", "roman", "iii"),  # C34 - Manual 2012, head "iii | July 10, 2012 (cont.)"
    ("383", "integer", "383"),  # CFR part 655, head "383 | Federal Highway Administration, DOT"
    ("Signalized Intersections: Informational Guide | 213", "integer", "213"),  # 04091.pdf, head
])
def test_families_match_lines_from_the_audit(line, family, number):
    found = {f: n for _, f, n in pages._candidates([line])}
    assert found.get(family) == number


@pytest.mark.parametrize("line, family", [
    ("Publication No. | FHWA-HRT-04-091", "chapter"),  # 04091.pdf cover: a publication number, not "04-091"
    ("Created 2-9-10 | Updated 9/30/19", "chapter"),  # NCDOTFinalRuleImplementation: a date
    ("48\"X48\" / W21-3", "chapter"),  # Division 11 drawings: a sign code
    ("A1-1, A1-3, B4-3, B4-4, B4-6, D2-1", "appendix"),  # bpguidebook index: best-practice ids
    ("Ill | I", "roman"),  # 010604.pdf, OCR noise
])
def test_families_do_not_match_codes_dates_and_noise(line, family):
    assert family not in {f for _, f, _ in pages._candidates([line])}


def test_numbers_parse_into_a_prefix_and_a_number():
    assert pages.parse_number("13") == ("", 13)
    assert pages.parse_number("5-13") == ("5", 13)
    assert pages.parse_number("A-3") == ("A", 3)
    assert pages.parse_number("A1") == ("A", 1)
    assert pages.parse_number("iv") == ("roman", 4)
    assert pages.parse_number("xlii") == ("roman", 42)
    assert pages.parse_number("C") == ("letter", 3)  # bpguidebook's cover labels A, B, C
    assert pages.parse_number("Ill") is None


def test_consistency_needs_steps_that_advance_with_the_pages():
    assert pages.consistent({1: "383", 2: "384", 4: "386"}, restart=False)
    assert pages.consistent({3: "2-47", 4: "2-48", 5: "3-1", 6: "3-2"}, restart=True)
    assert not pages.consistent({3: "2-47", 4: "2-48", 5: "3-1", 6: "3-2"}, restart=False)
    assert not pages.consistent({1: "W1-1", 2: "W1-1", 3: "W1-1"}, restart=True)
    assert not pages.consistent({1: "43", 2: "35", 3: "30", 4: "47"}, restart=False)  # Standard Specs line numbers
    assert not pages.consistent({4: "1", 21: "18"}, restart=False)  # two hits that happen to line up
    assert pages.consistent({4: "1", 21: "18"}, restart=False, min_hits=2)


def test_a_body_line_with_a_number_on_a_page_without_a_footer_is_not_taken_for_its_page_number(tmp_path):
    # The footer line runs 11-25 as a whole; p.5 has no footer and its edge line is body text ending in "45".
    numbers = [str(n) for n in range(11, 26)]
    expected = numbers[:4] + [None] + numbers[5:]
    for name, form in (("bare.pdf", "Part 2 | {}"), ("page.pdf", "Page {}")):
        footers = [form.format(n) for n in numbers]
        footers[4] = "a posted speed of 45"
        path = _pdf(tmp_path / name, footers=footers)
        assert [i.printed for i in pages.document_identities(path)] == expected


def test_labels_that_repeat_the_index_give_way_to_the_footer(tmp_path):
    labels = [{"startpage": 0, "prefix": "", "style": "D", "firstpagenum": 1}]
    path = _pdf(tmp_path / "default.pdf", footers=["2-1", "2-2", "2-3", ""], labels=labels)

    identities = pages.document_identities(path)

    assert [(i.printed, i.source) for i in identities] == [("2-1", "footer"), ("2-2", "footer"), ("2-3", "footer"),
                                                           ("4", "label")]


def test_uppercase_roman_labels_run_like_page_numbers(tmp_path):
    labels = [{"startpage": 0, "prefix": "", "style": "R", "firstpagenum": 1},
              {"startpage": 10, "prefix": "", "style": "D", "firstpagenum": 1}]
    path = _pdf(tmp_path / "front.pdf", footers=[""] * 12, labels=labels)

    printed = [i.printed for i in pages.document_identities(path)]

    assert printed == ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "1", "2"]


def test_words_and_badly_formed_numerals_are_not_roman():
    assert pages.roman_value("civil") is None
    assert pages.roman_value("iiii") is None
    assert pages.roman_value("Ill") is None
    assert pages.roman_value("xiv") == 14


def test_a_one_page_chapter_keeps_its_page_one(tmp_path):
    # TMP Part 3: Chapter 2 is one page, so "Page 1" follows "Page 1" (PDF p.116).
    footers = [f"Chapter 1 | Page {n}" for n in range(1, 6)] + ["Chapter 2 | Page 1", "Chapter 3 | Page 1",
                                                               "Chapter 3 | Page 2", "Chapter 3 | Page 3"]
    path = _pdf(tmp_path / "chapters.pdf", footers=footers)

    assert [i.printed for i in pages.document_identities(path)] == ["1", "2", "3", "4", "5", "1", "1", "2", "3"]
