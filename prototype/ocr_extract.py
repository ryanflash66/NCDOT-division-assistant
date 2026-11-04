"""Re-read chosen PDF pages with an OCR-capable extractor, for the image/table retrieval test (DAR-651).

    python prototype/ocr_extract.py --option pymupdf4llm-ocr --pages pages.json --out extracted.json
    python prototype/ocr_extract.py --option docling-ocr     --pages pages.json --out extracted.json

Runs in its own virtual environment, not .venv: pymupdf4llm turns OCR on by
itself as soon as an OCR engine (RapidOCR, Tesseract) is importable, so
installing one into .venv would silently change what `prototype.ingest` builds.
That venv needs pymupdf4llm==1.28.2 and pymupdf-layout (as .venv), rapidocr,
onnxruntime and docling. It imports nothing from the repo, so it runs as a plain
script; `prototype.image_table_check` reads its output.

--pages is a JSON list of {"division", "source", "page"} (1-based PDF page);
each document is read from hosted/documents/<division>/<source>. The output is
one row per page: {"division", "source", "page", "text", "seconds"}, where
`text` is the page's Markdown and `seconds` its share of the extractor's time
(the document's time divided by its pages read, model loading excluded).
"""

import argparse
import json
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List

DOCUMENTS_DIR = Path(__file__).resolve().parent.parent / "hosted" / "documents"
OCR_DPI = 200  # pymupdf4llm's default is 150; the scanned UAM attachments are small type


def _pymupdf4llm_ocr() -> Callable[[Path, List[int]], Dict[int, str]]:
    import pymupdf4llm
    from pymupdf4llm.ocr import rapidocr_api

    def read(path: Path, pages: List[int]) -> Dict[int, str]:
        # The same call as rag.loader's reader, plus the OCR engine. OCR only runs
        # on pages pymupdf4llm judges to need it (images or vector text, little text).
        chunks = pymupdf4llm.to_markdown(str(path), pages=[p - 1 for p in pages], page_chunks=True,
                                         show_progress=False, use_ocr=True, ocr_function=rapidocr_api.exec_ocr,
                                         ocr_dpi=OCR_DPI)
        out = {}
        for chunk in chunks:
            meta = chunk["metadata"]
            out[int(meta.get("page_number", meta.get("page")))] = chunk["text"]
        return out

    return read


def _docling_ocr() -> Callable[[Path, List[int]], Dict[int, str]]:
    import pymupdf
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions(do_ocr=True, do_table_structure=True, ocr_options=RapidOcrOptions())
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})

    def read(path: Path, pages: List[int]) -> Dict[int, str]:
        # Docling converts a whole file; copy just these pages into a small PDF so
        # the time is theirs, then map its page numbers back.
        with pymupdf.open(path) as source, pymupdf.open() as subset:
            for page in pages:
                subset.insert_pdf(source, from_page=page - 1, to_page=page - 1)
            with tempfile.TemporaryDirectory() as tmp:
                part = Path(tmp) / "pages.pdf"
                subset.save(part)
                document = converter.convert(part).document
        return {page: document.export_to_markdown(page_no=i) for i, page in enumerate(pages, 1)}

    return read


def _pymupdf4llm() -> Callable[[Path, List[int]], Dict[int, str]]:
    """The current reader (rag.loader's call, OCR off), as the baseline for --captions."""
    import pymupdf4llm

    def read(path: Path, pages: List[int]) -> Dict[int, str]:
        chunks = pymupdf4llm.to_markdown(str(path), pages=[p - 1 for p in pages], page_chunks=True,
                                         show_progress=False, use_ocr=False)
        return {int(c["metadata"].get("page_number", c["metadata"].get("page"))): c["text"] for c in chunks}

    return read


OPTIONS = {"pymupdf4llm": _pymupdf4llm, "pymupdf4llm-ocr": _pymupdf4llm_ocr, "docling-ocr": _docling_ocr}


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--option", choices=sorted(OPTIONS), required=True)
    parser.add_argument("--pages", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    wanted = defaultdict(set)
    for row in json.loads(args.pages.read_text(encoding="utf-8")):
        wanted[(row["division"], row["source"])].add(int(row["page"]))
    started = time.perf_counter()
    read = OPTIONS[args.option]()
    print(f"{args.option}: loaded in {time.perf_counter() - started:.1f}s", flush=True)
    rows = []
    for (division, source), pages in sorted(wanted.items()):
        pages = sorted(pages)
        started = time.perf_counter()
        texts = read(DOCUMENTS_DIR / division / source, pages)
        seconds = time.perf_counter() - started
        print(f"  {division}/{source}: {len(pages)} page(s) in {seconds:.1f}s", flush=True)
        rows += [{"division": division, "source": source, "page": page, "text": texts.get(page, ""),
                  "seconds": seconds / len(pages)} for page in pages]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    total = sum(r["seconds"] for r in rows)
    print(f"{len(rows)} pages, {total:.0f}s, {total / max(len(rows), 1):.2f}s per page -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
