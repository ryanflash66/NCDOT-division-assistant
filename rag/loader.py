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
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

from llama_index.core import Document, SimpleDirectoryReader
from llama_index.core.readers.base import BaseReader

from rag.classify import classify
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


def _file_extractor(files: List[Path], ocr: bool = False) -> Dict[str, object]:
    extractor: Dict[str, object] = {}
    unstructured_exts = {p.suffix.lower() for p in files if FORMATS[p.suffix.lower()].reader == "unstructured"}
    if unstructured_exts:
        from llama_index.readers.file import UnstructuredReader

        reader = UnstructuredReader()
        extractor.update({ext: reader for ext in unstructured_exts})
    pdf_exts = {ext for ext, fmt in FORMATS.items() if fmt.reader == "pdf"}
    extractor.update({ext: _PdfMarkdownReader(ocr=ocr) for ext in pdf_exts})
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

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None


# OCR resolution: pymupdf4llm's default is 150 dpi; the scanned UAM attachments are small type.
OCR_DPI = 200


class _PdfMarkdownReader(BaseReader):
    """One Document per page, as Markdown; tables become Markdown tables.

    Empty and "--" cells are kept, so every row has the table's full column count.

    With `ocr`, pages pymupdf4llm judges to need it (images or text drawn as
    outlines, little real text, no earlier OCR layer) are read with RapidOCR;
    other pages read exactly as without it. Without `ocr`, OCR is off even when
    an OCR engine is installed, as pymupdf4llm would otherwise turn it on by
    itself. DAR-651: 184 pages in 15 documents (scanned attachments, pictures of
    text) had no searchable text before.
    """

    def __init__(self, ocr: bool = False):
        super().__init__()
        self._ocr = ocr

    def load_data(self, file, extra_info=None, **_kwargs) -> List[Document]:
        import pymupdf4llm

        options = {"use_ocr": False}
        if self._ocr:
            from pymupdf4llm.ocr import rapidocr_api

            options = {"use_ocr": True, "ocr_function": rapidocr_api.exec_ocr, "ocr_dpi": OCR_DPI}
        pages = pymupdf4llm.to_markdown(str(file), page_chunks=True, show_progress=False, **options)
        rotated = _RotatedLines(file)
        try:
            return [
                Document(
                    # `<br>` is kept until the tables are cleaned: it marks rows stacked into
                    # one and the pieces of a rotated label (rag/table_rows.py).
                    text=clean_markdown_tables(_PDF_MARKUP.sub("", page["text"]),
                                               rotated.on(page["metadata"].get("page_number", page["metadata"].get("page")),
                                                          page["text"])),
                    metadata={
                        # "page" on pymupdf4llm's fallback path (no pymupdf.layout); both are 1-based.
                        "page_label": str(page["metadata"].get("page_number", page["metadata"].get("page"))),
                        "file_name": Path(file).name,
                        **(extra_info or {}),
                    },
                )
                for page in pages
            ]
        finally:
            rotated.close()


_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def markdown_sections(text: str) -> List[Tuple[Optional[str], str]]:
    """Split Markdown into (heading path, text) pairs, one per heading.

    The heading path joins the enclosing headings with " > ", e.g.
    "Ransomware Playbook > Containment". Text before the first heading has no
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


def load(data_dir: "str | Path", only: Optional[Iterable["str | Path"]] = None, ocr: bool = False) -> List[Document]:
    """Load every supported Document under data_dir, with its metadata attached.

    Files with unsupported extensions and hidden files or directories are skipped.
    Documents that produce no text are dropped. `only` limits loading to those
    files (paths under data_dir); metadata is still relative to data_dir. `ocr`
    reads PDF pages without a text layer with OCR (see _PdfMarkdownReader).
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
        file_extractor=_file_extractor(files, ocr),
        file_metadata=lambda path: document_metadata(_relative(data_dir, path)),
    )
    docs = [doc for doc in reader.load_data() if doc.text.strip()]
    for doc in docs:
        section = section_for(doc.metadata["source"], doc.metadata)
        if section:
            doc.metadata["section"] = section
    return docs
