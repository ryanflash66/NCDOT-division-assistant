"""Tests for the Document loader: the format table and what load() returns."""

import shutil

import pytest

from rag import loader

TEXT_EXTENSIONS = sorted(ext for ext, fmt in loader.FORMATS.items() if fmt.reader == "text")


def test_every_format_has_a_known_reader_and_doc_type():
    for ext, fmt in loader.FORMATS.items():
        assert ext.startswith(".") and ext == ext.lower()
        assert fmt.reader in {"default", "pdf", "text", "unstructured", "markdown", "sheets"}
        assert fmt.doc_type and fmt.doc_type != "other"
        assert fmt.requires in {None, "tesseract", "soffice", "pandoc"}


def test_supported_extensions_follow_tool_availability(monkeypatch):
    monkeypatch.setattr(loader.shutil, "which", lambda name: None)
    without_tools = loader.supported_extensions()
    monkeypatch.setattr(loader.shutil, "which", lambda name: f"/usr/bin/{name}")
    with_tools = loader.supported_extensions()

    assert with_tools == frozenset(loader.FORMATS)
    assert without_tools == frozenset(ext for ext, fmt in loader.FORMATS.items() if fmt.requires is None)
    assert ".png" not in without_tools and ".doc" not in without_tools
    assert ".md" in without_tools and ".html" in without_tools


def test_files_needing_a_missing_tool_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.shutil, "which", lambda name: None)
    (tmp_path / "keep.md").write_text("keep", encoding="utf-8")
    (tmp_path / "scan.png").write_bytes(b"not really a png")

    assert {d.metadata["source"] for d in loader.load(tmp_path)} == {"keep.md"}


@pytest.mark.parametrize("ext", TEXT_EXTENSIONS + [".md"])
def test_text_formats_yield_text(tmp_path, ext):
    (tmp_path / f"sample{ext}").write_text("hello work zone inspectors", encoding="utf-8")

    docs = loader.load(tmp_path)

    assert docs
    assert "hello work zone inspectors" in " ".join(d.text for d in docs)
    assert docs[0].metadata["doc_type"] == loader.FORMATS[ext].doc_type


def test_unsupported_and_hidden_files_are_skipped(tmp_path):
    (tmp_path / "keep.md").write_text("keep", encoding="utf-8")
    (tmp_path / "payload.exe").write_bytes(b"MZ")
    (tmp_path / ".secret.md").write_text("hidden", encoding="utf-8")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "x.md").write_text("hidden", encoding="utf-8")

    docs = loader.load(tmp_path)

    assert {d.metadata["source"] for d in docs} == {"keep.md"}


def test_empty_documents_are_dropped(tmp_path):
    (tmp_path / "blank.txt").write_text("   \n", encoding="utf-8")
    assert loader.load(tmp_path) == []


def test_metadata_uses_relative_posix_source(tmp_path):
    (tmp_path / "utilities").mkdir()
    (tmp_path / "utilities" / "relocation.md").write_text("move the poles", encoding="utf-8")

    meta = loader.load(tmp_path)[0].metadata

    assert meta["source"] == "utilities/relocation.md"
    assert meta["filename"] == "relocation.md"
    assert meta["topic"] == "utilities"


def test_docx_uses_default_reader(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Close the right lane before paving.")
    document.save(tmp_path / "lane_closure.docx")

    docs = loader.load(tmp_path)

    assert "Close the right lane before paving." in docs[0].text
    assert docs[0].metadata["doc_type"] == "word"


def test_pptx_yields_slide_text(tmp_path):
    pptx = pytest.importorskip("pptx")
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Tabletop exercise"
    deck.save(tmp_path / "tabletop.pptx")

    docs = loader.load(tmp_path)

    assert "Tabletop exercise" in " ".join(d.text for d in docs)
    assert docs[0].metadata["doc_type"] == "powerpoint"


CURVE_TABLE = [
    ["RADIUS", "40", "45", "50"],
    ["2860", "1.1", "1.1", "1.1"],
    ["1430", "1.2", "1.2", "--"],
    ["380", "1.5", "--", ""],
]


def _write_pdf(path, pages):
    """Write a PDF with one page per entry; an entry is a heading plus an optional ruled table."""
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    for heading, rows in pages:
        page = pdf.new_page()
        page.insert_text((72, 72), heading, fontsize=12)
        left, top, col_w, row_h = 72, 100, 80, 20
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                rect = pymupdf.Rect(left + c * col_w, top + r * row_h, left + (c + 1) * col_w, top + (r + 1) * row_h)
                page.draw_rect(rect, color=(0, 0, 0), width=0.8)
                if cell:
                    page.insert_text((rect.x0 + 4, rect.y1 - 6), cell, fontsize=10)
    pdf.save(path)


def _table_rows(markdown):
    rows = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|")]
    # Drop only the outer pipes: a trailing empty cell renders as "||".
    return [[cell.strip() for cell in row[1:-1].split("|")] for row in rows if not set(row) <= set("|-: ")]


def test_pdf_tables_become_aligned_markdown_tables(tmp_path):
    _write_pdf(tmp_path / "manual.pdf", [("Table 3-2 Horizontal Curve Adjustments", CURVE_TABLE)])

    docs = loader.load(tmp_path)

    assert len(docs) == 1
    assert "Table 3-2 Horizontal Curve Adjustments" in docs[0].text
    assert _table_rows(docs[0].text) == CURVE_TABLE
    assert docs[0].metadata["doc_type"] == "pdf"
    assert docs[0].metadata["source"] == "manual.pdf"


def test_pdf_yields_one_document_per_page_with_page_label(tmp_path):
    _write_pdf(tmp_path / "manual.pdf", [("Chapter one intro", []), ("Chapter two table", CURVE_TABLE), ("Chapter three end", [])])

    docs = loader.load(tmp_path)

    assert [d.metadata["page_label"] for d in docs] == ["1", "2", "3"]
    assert "Chapter one intro" in docs[0].text
    assert "Chapter two table" in docs[1].text and _table_rows(docs[1].text) == CURVE_TABLE
    assert "Chapter three end" in docs[2].text
    assert all(d.metadata["file_name"] == "manual.pdf" for d in docs)


def test_only_limits_loading_to_the_given_files(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "keep.md").write_text("# Keep\nkept text", encoding="utf-8")
    (tmp_path / "skip.txt").write_text("skipped text", encoding="utf-8")

    docs = loader.load(tmp_path, only=[tmp_path / "sub" / "keep.md"])

    assert {d.metadata["source"] for d in docs} == {"sub/keep.md"}


def test_pdf_reader_strips_inline_markup_and_accepts_legacy_page_key(tmp_path, monkeypatch):
    pymupdf4llm = pytest.importorskip("pymupdf4llm")
    chunks = [{"text": "<mark>Part 2</mark> �\n|Iowa|10 inches<br>(informal)|", "metadata": {"page": 7}}]
    monkeypatch.setattr(pymupdf4llm, "to_markdown", lambda *_args, **_kwargs: chunks)
    (tmp_path / "manual.pdf").write_bytes(b"%PDF-1.7")

    docs = loader.load(tmp_path)

    assert docs[0].text == "Part 2 \n|Iowa|10 inches (informal)|"
    assert docs[0].metadata["page_label"] == "7"


def test_html_uses_unstructured(tmp_path):
    (tmp_path / "flagging.html").write_text(
        "<html><body><h1>Flagging</h1><p>Flaggers wear high-visibility apparel.</p></body></html>",
        encoding="utf-8",
    )
    docs = loader.load(tmp_path)
    assert "Flaggers wear high-visibility apparel." in " ".join(d.text for d in docs)
    assert docs[0].metadata["doc_type"] == "html"


def test_eml_uses_unstructured(tmp_path):
    (tmp_path / "permit.eml").write_text(
        "From: utilities@example.com\r\nTo: district@example.com\r\nSubject: Permit\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\nThe encroachment permit is approved.\r\n",
        encoding="utf-8",
        newline="",
    )
    docs = loader.load(tmp_path)
    assert "The encroachment permit is approved." in " ".join(d.text for d in docs)
    assert docs[0].metadata["doc_type"] == "email"


def test_xlsx_yields_sheet_text(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.append(["device", "owner"])
    book.active.append(["drum", "wztc-crew"])
    book.save(tmp_path / "devices.xlsx")

    docs = loader.load(tmp_path)

    assert "wztc-crew" in " ".join(d.text for d in docs)
    assert docs[0].metadata["doc_type"] == "spreadsheet"


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_image_ocr(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (600, 120), "white")
    ImageDraw.Draw(image).text((10, 30), "SPEED LIMIT 45", fill="black", font=ImageFont.load_default(size=40))
    image.save(tmp_path / "sign.png")

    docs = loader.load(tmp_path)

    assert "SPEED" in " ".join(d.text for d in docs).upper()


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_legacy_doc_via_libreoffice(tmp_path):
    docx = pytest.importorskip("docx")
    import subprocess

    document = docx.Document()
    document.add_paragraph("Legacy procedure text.")
    document.save(tmp_path / "src.docx")
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "doc", "--outdir", str(tmp_path / "out"), str(tmp_path / "src.docx")],
        check=True,
    )

    docs = loader.load(tmp_path / "out")

    assert "Legacy procedure text." in " ".join(d.text for d in docs)


# --- section metadata ---------------------------------------------------------


def test_document_metadata_omits_section_unless_given():
    assert "section" not in loader.document_metadata("notes.txt")
    assert loader.document_metadata("notes.txt", section="Intro")["section"] == "Intro"


@pytest.mark.parametrize(
    "path, reader_metadata, expected",
    [
        ("manual.pdf", {"page_label": "12"}, "Page 12"),
        ("manual.pdf", {"page_label": "iv"}, "Page iv"),
        ("deck.pptx", {"page_label": 3}, "Slide 3"),
        ("manual.md", {"section": "Work Zones > Setup"}, "Work Zones > Setup"),
        ("manual.pdf", {}, None),
        ("notes.txt", {"page_label": "1"}, None),
    ],
)
def test_section_for(path, reader_metadata, expected):
    assert loader.section_for(path, reader_metadata) == expected


def test_markdown_sections_follow_heading_path():
    text = (
        "Preamble line.\n"
        "# Work Zone Manual\n"
        "Overview text.\n"
        "## Setup\n"
        "Place the taper.\n"
        "```\n# not a heading\n```\n"
        "### Signs\n"
        "Space signs 500 ft apart.\n"
        "## Removal\n"
        "Remove devices.\n"
    )

    sections = loader.markdown_sections(text)

    assert [s for s, _ in sections] == [
        None,
        "Work Zone Manual",
        "Work Zone Manual > Setup",
        "Work Zone Manual > Setup > Signs",
        "Work Zone Manual > Removal",
    ]
    setup = dict(sections)["Work Zone Manual > Setup"]
    assert setup.startswith("## Setup\n")
    assert "# not a heading" in setup and "Place the taper." in setup


def test_markdown_sections_skip_heading_only_sections():
    sections = loader.markdown_sections("# Manual\n\n## Setup\nPlace the taper.\n")

    assert [s for s, _ in sections] == ["Manual > Setup"]


def test_markdown_sections_keep_trailing_hash_in_heading_text():
    sections = loader.markdown_sections("# Learn C#\nbody\n## Closed ##\nmore\n")

    assert [s for s, _ in sections] == ["Learn C#", "Learn C# > Closed"]


def test_markdown_sections_nested_fences_hide_headings():
    text = "# Top\n````md\n```\n# inner comment\n```\n````\nafter\n~~~\n# tilde comment\n~~~\n"

    sections = loader.markdown_sections(text)

    assert [s for s, _ in sections] == ["Top"]
    assert "# inner comment" in sections[0][1] and "# tilde comment" in sections[0][1]


def test_markdown_documents_carry_heading_section(tmp_path):
    (tmp_path / "work_zone.md").write_text(
        "# Work Zone Manual\n\n## Setup\n\nPlace advance warning signs.\n\n## Removal\n\nRemove devices in reverse order.\n",
        encoding="utf-8",
    )

    docs = loader.load(tmp_path)

    by_section = {d.metadata["section"]: d.text for d in docs}
    assert set(by_section) == {"Work Zone Manual > Setup", "Work Zone Manual > Removal"}
    assert "Place advance warning signs." in by_section["Work Zone Manual > Setup"]
    assert "Remove devices in reverse order." in by_section["Work Zone Manual > Removal"]
    assert all(d.metadata["source"] == "work_zone.md" for d in docs)


def test_markdown_without_headings_has_no_section(tmp_path):
    (tmp_path / "notes.md").write_text("just some notes", encoding="utf-8")

    (doc,) = loader.load(tmp_path)

    assert "section" not in doc.metadata


def test_pptx_documents_carry_slide_section(tmp_path):
    pptx = pytest.importorskip("pptx")
    deck = pptx.Presentation()
    for title in ("Detection", "Escalation"):
        deck.slides.add_slide(deck.slide_layouts[1]).shapes.title.text = title
    deck.save(tmp_path / "tabletop.pptx")

    docs = loader.load(tmp_path)

    sections = {d.metadata["section"]: d.text for d in docs}
    assert "Detection" in sections["Slide 1"]
    assert "Escalation" in sections["Slide 2"]


def test_xlsx_documents_carry_sheet_section(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.title = "Contacts"
    book.active.append(["team", "phone"])
    book.active.append(["utilities", "555-0100"])
    devices = book.create_sheet("Devices")
    devices.append(["device", "owner"])
    devices.append(["drum", "wztc-crew"])
    book.save(tmp_path / "devices.xlsx")

    docs = loader.load(tmp_path)

    sections = {d.metadata["section"]: d.text for d in docs}
    assert set(sections) == {"Contacts", "Devices"}
    assert "555-0100" in sections["Contacts"] and "wztc-crew" not in sections["Contacts"]
    assert "wztc-crew" in sections["Devices"]


def test_pdf_documents_carry_page_section(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    for text in ("Page one text.", "Page two text."):
        pdf.new_page().insert_text((72, 72), text)
    pdf.save(tmp_path / "manual.pdf")

    docs = loader.load(tmp_path)

    sections = {d.metadata["section"]: d.text for d in docs}
    assert "Page one text." in sections["Page 1"]
    assert "Page two text." in sections["Page 2"]
    assert all("page_label" in d.metadata for d in docs)


def test_plain_text_has_no_section(tmp_path):
    (tmp_path / "notes.txt").write_text("rotate keys", encoding="utf-8")

    (doc,) = loader.load(tmp_path)

    assert "section" not in doc.metadata
