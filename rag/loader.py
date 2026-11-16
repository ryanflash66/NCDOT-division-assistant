"""Document loader: the single table of supported file formats.

Each extension maps to how it is read and the doc_type it is labelled with.
The ingest allowlist, the Retrieval index and the Chainlit UI all derive from
this table.

A format with `requires` set is only supported when that program is on PATH
(Tesseract for image OCR, LibreOffice for .doc/.ppt, pandoc for .rtf/.odt).

Readers:
  "default"      -- LlamaIndex's built-in reader for the extension
  "pdf"          -- pymupdf4llm: one Markdown Document per page, tables kept as
                    Markdown tables so cells stay in their columns
  "text"         -- read as plain UTF-8 text
  "unstructured" -- UnstructuredReader, for formats with no usable built-in reader
  "markdown"     -- split into one Document per heading section
  "sheets"       -- UnstructuredReader, one Document per worksheet

Documents carry a `section` naming where in the file they came from, when the
format has one: the heading path for Markdown, "Slide N" for .pptx, the sheet
name for spreadsheets and "Page N" for PDFs.
"""

import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

from llama_index.core import Document, SimpleDirectoryReader
from llama_index.core.readers.base import BaseReader

from rag.classify import classify
from rag.table_notes import insert_after_last_table, missing_notes
from rag.tables import clean_markdown_tables

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileFormat:
    doc_type: str
    reader: str
    # External program the reader shells out to; the format is only supported
    # on hosts where it is on PATH.
    requires: Optional[str] = None


FORMATS: Dict[str, FileFormat] = {
    # Documents
    ".pdf": FileFormat("pdf", "pdf"),
    ".docx": FileFormat("word", "default"),
    ".doc": FileFormat("word", "unstructured", requires="soffice"),
    ".md": FileFormat("markdown", "markdown"),
    ".txt": FileFormat("text", "text"),
    ".rtf": FileFormat("rtf", "unstructured", requires="pandoc"),
    ".odt": FileFormat("opendocument", "unstructured", requires="pandoc"),
    ".html": FileFormat("html", "unstructured"),
    ".htm": FileFormat("html", "unstructured"),
    # Presentations
    ".pptx": FileFormat("powerpoint", "default"),
    ".ppt": FileFormat("powerpoint", "unstructured", requires="soffice"),
    # Spreadsheets and data
    ".csv": FileFormat("csv", "default"),
    ".xlsx": FileFormat("spreadsheet", "sheets"),
    ".xls": FileFormat("spreadsheet", "sheets"),
    ".json": FileFormat("json", "text"),
    ".jsonl": FileFormat("jsonl", "text"),
    # Configuration, scripts and logs
    ".xml": FileFormat("xml", "text"),
    ".yaml": FileFormat("yaml", "text"),
    ".yml": FileFormat("yaml", "text"),
    ".conf": FileFormat("config", "text"),
    ".config": FileFormat("config", "text"),
    ".ini": FileFormat("config", "text"),
    ".ps1": FileFormat("script", "text"),
    ".sh": FileFormat("script", "text"),
    ".bat": FileFormat("script", "text"),
    ".cmd": FileFormat("script", "text"),
    ".py": FileFormat("script", "text"),
    ".log": FileFormat("log", "text"),
    # Email
    ".eml": FileFormat("email", "unstructured"),
    ".msg": FileFormat("email", "unstructured"),
    # Images (OCR)
    ".png": FileFormat("image", "unstructured", requires="tesseract"),
    ".jpg": FileFormat("image", "unstructured", requires="tesseract"),
    ".jpeg": FileFormat("image", "unstructured", requires="tesseract"),
    ".gif": FileFormat("image", "unstructured", requires="tesseract"),
    ".bmp": FileFormat("image", "unstructured", requires="tesseract"),
    ".tiff": FileFormat("image", "unstructured", requires="tesseract"),
}


def is_available(fmt: FileFormat) -> bool:
    return fmt.requires is None or shutil.which(fmt.requires) is not None


def supported_extensions() -> FrozenSet[str]:
    """Extensions this host can actually read (formats whose tool is missing are left out)."""
    return frozenset(ext for ext, fmt in FORMATS.items() if is_available(fmt))


def doc_type(path: "str | PurePath") -> str:
    fmt = FORMATS.get(PurePath(path).suffix.lower())
    return fmt.doc_type if fmt else "other"


def _relative(data_dir: Path, file_path: str) -> PurePath:
    return PurePath(os.path.relpath(os.path.abspath(file_path), data_dir))


def document_metadata(relative_path: "str | PurePath", section: Optional[str] = None) -> Dict[str, str]:
    """Metadata stored on every chunk of a Document.

    `section` is left out entirely when the format has no meaningful one.
    """
    rel = PurePath(relative_path)
    metadata = {
        "source": rel.as_posix(),
        "filename": rel.name,
        "doc_type": doc_type(rel),
        **classify(rel).as_metadata(),
    }
    if section:
        metadata["section"] = section
    return metadata


def section_for(relative_path: "str | PurePath", reader_metadata: Dict) -> Optional[str]:
    """The section a Document came from, from the metadata its reader produced.

    Readers that know the section (Markdown, spreadsheets) set it directly;
    paged formats get it from the reader's `page_label`.
    """
    if reader_metadata.get("section"):
        return str(reader_metadata["section"])
    label = reader_metadata.get("page_label")
    if label in (None, ""):
        return None
    suffix = PurePath(relative_path).suffix.lower()
    if suffix == ".pdf":
        return f"Page {label}"
    if suffix == ".pptx":
        return f"Slide {label}"
    return None


def _supported_files(data_dir: Path) -> List[Path]:
    supported = supported_extensions()
    return [
        p for p in data_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in supported
        and not any(part.startswith(".") for part in p.relative_to(data_dir).parts)
    ]


def _file_extractor(files: List[Path], ocr: bool = False, tables: bool = False) -> Dict[str, object]:
    extractor: Dict[str, object] = {}
    unstructured_exts = {p.suffix.lower() for p in files if FORMATS[p.suffix.lower()].reader == "unstructured"}
    if unstructured_exts:
        from llama_index.readers.file import UnstructuredReader

        reader = UnstructuredReader()
        extractor.update({ext: reader for ext in unstructured_exts})
    pdf_exts = {ext for ext, fmt in FORMATS.items() if fmt.reader == "pdf"}
    extractor.update({ext: _PdfMarkdownReader(ocr=ocr, tables=tables) for ext in pdf_exts})
    # Keep "text" formats away from any built-in reader keyed on the same extension.
    text_exts = {ext for ext, fmt in FORMATS.items() if fmt.reader == "text"}
    extractor.update({ext: _PlainTextReader() for ext in text_exts})
    extractor.update({ext: _MarkdownReader() for ext, fmt in FORMATS.items() if fmt.reader == "markdown"})
    sheet_exts = {p.suffix.lower() for p in files if FORMATS[p.suffix.lower()].reader == "sheets"}
    if sheet_exts:
        extractor.update({ext: _SheetReader() for ext in sheet_exts})
    return extractor


class _PlainTextReader(BaseReader):
    def load_data(self, file, extra_info=None, **_kwargs) -> List[Document]:
        text = Path(file).read_text(encoding="utf-8", errors="replace")
        return [Document(text=text, metadata=extra_info or {})]


# Inline HTML pymupdf4llm emits for highlighted/underlined text and in-cell line
# breaks; it only adds noise to embeddings. U+FFFD marks glyphs it couldn't map.
_PDF_MARKUP = re.compile(r"</?(?:mark|u)>|\ufffd")


class _RotatedLines:
    """Text-layer lines that do not run left to right, per page, read only for pages with a table.

    TMP Design Manual p. 37: the row header "Offset (ft)" is printed
    vertically (line dir (0, -1)) and is whole in the text layer, while the
    Markdown grid scatters it over four cells; rag.table_rows uses these
    lines to recognise and remove the pieces.
    """

    def __init__(self, file):
        self._file = file
        self._doc = None

    def on(self, page_number, markdown: str) -> List[str]:
        if not page_number or not any(line.lstrip().startswith("|") for line in markdown.split("\n")):
            return []
        try:
            import pymupdf

            if self._doc is None:
                self._doc = pymupdf.open(str(self._file))
            page = self._doc[int(page_number) - 1]
            lines = [line for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])]
            rotated = [
                "".join(span["text"] for span in line["spans"]).strip()
                for line in lines
                if tuple(round(x, 2) for x in line["dir"]) != (1.0, 0.0)
            ]
            # On a page set sideways most lines are "rotated", and they are the
            # table's own cells, not a label beside it (TMP p. 37 has 1 of ~150).
            return rotated if len(rotated) <= max(3, len(lines) // 5) else []
        except Exception:  # the grid is still cleaned without them
            log.debug("no text layer for %s p. %s", self._file, page_number, exc_info=True)
            return []

    def text_lines(self, page_number, markdown: str) -> List[str]:
        """All of the page's text-layer lines, read only for a page with a table ([] otherwise).

        rag.table_notes.missing_notes looks in them for a table note the
        Markdown dropped (Standard Specifications p.580, DAR-717).
        """
        if not page_number or not any(line.lstrip().startswith("|") for line in markdown.split("\n")):
            return []
        try:
            import pymupdf

            if self._doc is None:
                self._doc = pymupdf.open(str(self._file))
            return self._doc[int(page_number) - 1].get_text("text").split("\n")
        except Exception:  # the page is read as before without them
            log.debug("no text layer for %s p. %s", self._file, page_number, exc_info=True)
            return []

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None


# OCR resolution: pymupdf4llm's default is 150 dpi; the scanned UAM attachments are small type.
OCR_DPI = 200
# Page notes for the index build (rag.ocr), not words to embed or to show a model.
_OCR_KEYS = ("ocr_degrees", "ocr_confidence", "flags")


class _PdfMarkdownReader(BaseReader):
    """One Document per page, as Markdown; tables become Markdown tables.

    Empty and "--" cells are kept, so every row has the table's full column count.

    With `ocr`, pages pymupdf4llm judges to need it (images or text drawn as
    outlines, little real text, no earlier OCR layer) are read with RapidOCR;
    other pages read exactly as without it. Without `ocr`, OCR is off even when
    an OCR engine is installed, as pymupdf4llm would otherwise turn it on by
    itself. DAR-651: 184 pages in 15 documents (scanned attachments, pictures of
    text) had no searchable text before. DAR-658: OCR tries the page's other
    orientations when the first reading is poor or sideways (rag.ocr); each OCR'd
    page's metadata gets `ocr_degrees`, `ocr_confidence` and, when it read badly
    or turned, `flags` ("ocr_low_conf", "rotated").
    """

    def __init__(self, ocr: bool = False, tables: bool = False):
        super().__init__()
        self._ocr = ocr
        self._tables = tables

    def load_data(self, file, extra_info=None, **_kwargs) -> List[Document]:
        import pymupdf4llm

        options = {"use_ocr": False}
        ocr = None
        if self._ocr:
            from rag.ocr import OrientedOcr

            ocr = OrientedOcr()
            options = {"use_ocr": True, "ocr_function": ocr, "ocr_dpi": OCR_DPI}
        pages = pymupdf4llm.to_markdown(str(file), page_chunks=True, show_progress=False, **options)
        boxes = table_boxes(file, pages) if self._tables else {}
        rotated = _RotatedLines(file)
        try:
            documents = []
            for page in pages:
                # "page" on pymupdf4llm's fallback path (no pymupdf.layout); both are 1-based.
                number = page["metadata"].get("page_number", page["metadata"].get("page"))
                label = str(number)
                text = page["text"]
                metadata = {"page_label": label, "file_name": Path(file).name}
                if number in boxes:
                    metadata["table_bboxes"] = boxes[number]
                result = ocr.pages.get(int(label) - 1) if ocr is not None and label.isdigit() else None
                if result is not None:
                    # A sideways drawing read turned upright, or sideways labels, can't go back onto the page at
                    # its boxes, so its text follows the page's own (rag.ocr).
                    turned = ocr.appended_text(result.number)
                    text = f"{text.rstrip()}\n\n{turned}\n" if turned else text
                    metadata.update(ocr_degrees=result.degrees, ocr_confidence=round(result.confidence, 3))
                    if result.flags:
                        metadata["flags"] = ",".join(result.flags)
                # A table note the Markdown left out goes back under the page's last table (DAR-717).
                notes = missing_notes(text, rotated.text_lines(number, page["text"]))
                if notes:
                    text = insert_after_last_table(text, notes)
                documents.append(Document(
                    # `<br>` is kept until the tables are cleaned: it marks rows stacked into
                    # one and the pieces of a rotated label (rag/table_rows.py).
                    text=clean_markdown_tables(_PDF_MARKUP.sub("", text), rotated.on(number, page["text"])),
                    metadata={**metadata, **(extra_info or {})},
                    excluded_embed_metadata_keys=list(_OCR_KEYS),
                    excluded_llm_metadata_keys=list(_OCR_KEYS),
                ))
            return documents
        finally:
            rotated.close()


# Table detection with pymupdf's own find_tables (the fallback when pymupdf4llm
# gives no layout boxes) stops after this many pages or seconds per document:
# it costs about 0.13 s per page of the 706-page Legal Guide, and a page drawn
# as thousands of vector paths can take minutes on its own. Pages past the cap
# carry no boxes, so only the geometry merge signal is missing for them.
TABLE_BOXES_MAX_PAGES = 1000
TABLE_BOXES_MAX_SECONDS = 120


def table_boxes(file, pages: List[Dict]) -> Dict[int, List[List[float]]]:
    """Per 1-based page number, each table's [x0, y0, x1, y1] as fractions of the page size, top to bottom.

    rag.table_merge reads them to tell a table that runs off the bottom of one
    page onto the top of the next. pymupdf4llm 1.28 lists every layout block
    of a page with its class in `page_boxes`, so the table boxes come from the
    pass it already made; without that key (older versions, the no-layout
    fallback) pymupdf's find_tables runs on each page, guarded and capped.
    """
    import pymupdf

    boxes: Dict[int, List[List[float]]] = {}
    started = time.perf_counter()
    with pymupdf.open(str(file)) as pdf:
        for n, page in enumerate(pages):
            number = page["metadata"].get("page_number", page["metadata"].get("page"))
            if not isinstance(number, int) or not 1 <= number <= pdf.page_count:
                continue
            try:
                rect = pdf[number - 1].rect
                width, height = rect.width or 1.0, rect.height or 1.0
                if "page_boxes" in page:
                    found = [b["bbox"] for b in page["page_boxes"] if b.get("class") == "table"]
                elif n < TABLE_BOXES_MAX_PAGES and time.perf_counter() - started < TABLE_BOXES_MAX_SECONDS:
                    found = [t.bbox for t in pdf[number - 1].find_tables().tables]
                else:
                    continue
            except Exception:  # a page pymupdf cannot analyse keeps no boxes rather than stopping the build
                continue
            boxes[number] = sorted(
                [[round(x0 / width, 4), round(y0 / height, 4), round(x1 / width, 4), round(y1 / height, 4)]
                 for x0, y0, x1, y1 in found],
                key=lambda b: b[1],
            )
    return boxes


_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def markdown_sections(text: str) -> List[Tuple[Optional[str], str]]:
    """Split Markdown into (heading path, text) pairs, one per heading.

    The heading path joins the enclosing headings with " > ", e.g.
    "Work Zone Manual > Setup". Text before the first heading has no
    path. Headings inside fenced code blocks are ignored; text is kept verbatim.
    """
    sections: List[Tuple[Optional[str], str]] = []
    path: List[Tuple[int, str]] = []
    heading_line = ""
    lines: List[str] = []
    fence: Optional[str] = None

    def flush() -> None:
        # A heading directly followed by a subheading has no text of its own.
        body = "\n".join(lines).strip()
        if body:
            text = f"{heading_line.strip()}\n{body}" if heading_line else body
            sections.append((" > ".join(title for _, title in path) or None, text))

    for line in text.splitlines():
        fence_match = _FENCE.match(line)
        if fence is not None:
            # A fence closes on a bare run of its own character, at least as long.
            run = fence_match.group(1) if fence_match else ""
            if run[:1] == fence[:1] and len(run) >= len(fence) and not line[fence_match.end():].strip():
                fence = None
            lines.append(line)
            continue
        if fence_match:
            fence = fence_match.group(1)
            lines.append(line)
            continue
        heading = _HEADING.match(line)
        if heading and heading.group(2):
            flush()
            lines = []
            heading_line = line
            level = len(heading.group(1))
            path = [(lvl, title) for lvl, title in path if lvl < level] + [(level, heading.group(2))]
            continue
        lines.append(line)
    flush()
    return sections


class _MarkdownReader(BaseReader):
    def load_data(self, file, extra_info=None, **_kwargs) -> List[Document]:
        text = Path(file).read_text(encoding="utf-8", errors="replace")
        docs = []
        for section, body in markdown_sections(text):
            metadata = dict(extra_info or {})
            if section:
                metadata["section"] = section
            docs.append(Document(text=body, metadata=metadata))
        return docs


class _SheetReader(BaseReader):
    """One Document per worksheet, with the sheet name as its section."""

    def load_data(self, file, extra_info=None, **_kwargs) -> List[Document]:
        from unstructured.partition.auto import partition

        sheets: Dict[str, List[str]] = {}
        for element in partition(filename=str(file)):
            name = getattr(element.metadata, "page_name", None) or ""
            sheets.setdefault(name, []).append(" ".join(str(element).split()))
        docs = []
        for name, chunks in sheets.items():
            metadata = dict(extra_info or {})
            if name:
                metadata["section"] = name
            docs.append(Document(text="\n\n".join(chunks), metadata=metadata))
        return docs


def load(data_dir: "str | Path", only: Optional[Iterable["str | Path"]] = None, ocr: bool = False,
         tables: bool = False) -> List[Document]:
    """Load every supported Document under data_dir, with its metadata attached.

    Files with unsupported extensions and hidden files or directories are skipped.
    Documents that produce no text are dropped. `only` limits loading to those
    files (paths under data_dir); metadata is still relative to data_dir. `ocr`
    reads PDF pages without a text layer with OCR (see _PdfMarkdownReader).
    `tables` adds each PDF page's table boxes as `table_bboxes` metadata (see
    table_boxes) for rag.table_merge; it is off by default as the list is not a
    value the Chainlit app's Chroma store accepts in metadata.
    """
    data_dir = Path(data_dir).resolve()
    files = _supported_files(data_dir)
    if only is not None:
        wanted = {Path(f).resolve() for f in only}
        files = [p for p in files if p.resolve() in wanted]
    if not files:
        return []

    reader = SimpleDirectoryReader(
        input_files=[str(p) for p in files],
        file_extractor=_file_extractor(files, ocr, tables),
        file_metadata=lambda path: document_metadata(_relative(data_dir, path)),
    )
    docs = [doc for doc in reader.load_data() if doc.text.strip()]
    for doc in docs:
        section = section_for(doc.metadata["source"], doc.metadata)
        if section:
            doc.metadata["section"] = section
    return docs
