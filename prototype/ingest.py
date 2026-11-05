"""Build the hosted demo's index offline from each division's documents.

    py -m prototype.ingest [--division ID ...] [--out hosted/index] [--compare] [--timings FILE]

The divisions and their documents come from hosted/divrag/divisions.py; each
document is read from hosted/documents/<division id>/<file> (where
hosted/scripts/fetch_documents.py downloads it), or from DATA_DIR (default
data/) when it isn't there, as older checkouts kept every PDF in data/. Documents are
read and chunked as the Chainlit app does (rag.loader's PDF-to-Markdown reader,
rag.tables' table-aware splitter) but into 512-token chunks, tagged with their division and the numbered section heading in
effect, embedded with the hosted app's embedder and saved as one index
(chunks.json + vectors.npy, plus the keyword index bm25.npz) that the hosted
app loads. A chunk on a page with figure or table captions also gets a
`context` line naming the document, page and captions, embedded with its text.
--reuse keeps the vectors of chunks that haven't changed. Building the index needs
requirements.txt (llama-index, pymupdf4llm) as well as hosted/requirements.txt;
the hosted app needs only the latter.

--compare also embeds a sample of the chunks and a few questions with
sentence-transformers (the Chainlit app's embedder) and prints the cosine
similarity between the two models' vectors.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from dotenv import load_dotenv

from prototype import HOSTED_DIR  # noqa: F401  (puts hosted/ on sys.path)
from divrag.divisions import BY_ID, DIVISIONS, DOCUMENTS_DIR, Division, Document
from divrag.embedder import Embedder
from divrag.index_file import IndexFile, search_text
from rag import loader
from rag.config import AppConfig, load_config
from rag.table_merge import merge_continued_tables, page_lines, page_span
from rag.tables import TableAwareSplitter

DEFAULT_OUT = HOSTED_DIR / "index"
# Smaller than the Chainlit app's 1024-token chunks: bge-small (and the
# reranker) read only the first 512 tokens of a passage, so with 1024-token
# chunks a rule near the end of a page was never embedded (UAM 3.6.4.1, the lane
# closure distances, ranked below 40th). Tables still get chunks of their own.
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
_COMPARE_SAMPLE = 64
_COMPARE_QUESTIONS = [
    "What is the minimum acceleration lane for an interstate entrance ramp in a work zone?",
    "What are the dimensions of the NC-PCB concrete barrier?",
    "How long should a merging taper be?",
]
# A Markdown heading for a numbered section or an appendix, as pymupdf4llm
# renders the manuals' headings: "## **3.6.4.1 Lane and Road Closures**",
# "# 5.6.3 Assessing ...", "#### **Appendix B. Figures**".
_SECTION_HEADING = re.compile(
    r"^#{1,6}\s+\**\s*((?:\d+(?:\.\d+)+\.?|Appendix\s+[A-Z]\.?)\s+[^*\n]+?)\s*\**\s*$", re.MULTILINE
)
_MAX_SECTIONS = 3
# A figure or table caption on its own line, as the manuals print them:
# "Figure 5 – NC-PCB impact design table for CONCRETE pavement", "TABLE 3 (continued)".
_CAPTION = re.compile(r"^[#*\s]*((?:Figure|FIGURE|Table|TABLE|Exhibit)\s+[0-9A-Z][\w.\-]*\b.*?)[*\s]*$", re.MULTILINE)
# Longer lines that start "Figure 3 ..." are prose referring to a figure, not its caption.
_MAX_CAPTION_CHARS = 150
_MAX_CAPTIONS = 3


def captions(text: str) -> List[str]:
    """The page's figure and table captions, in order, without Markdown marks."""
    text = re.sub(r"</?(?:u|mark|b|i|em|strong)>", "", text)  # pymupdf4llm underlines the TMP manual's captions
    found = [" ".join(m.group(1).replace("**", "").split()) for m in _CAPTION.finditer(text)]
    return list(dict.fromkeys(c for c in found if 8 < len(c) <= _MAX_CAPTION_CHARS))[:_MAX_CAPTIONS]


def context_line(title: str, page: Optional[int], names: List[str]) -> str:
    """The line embedded (and reranked, and shown to the model) before each chunk of a page with captions.

    The TMP manual's asphalt (p. 37) and concrete (p. 38) deflection tables
    differ only in their numbers and the caption under each table, which the
    splitter leaves in a chunk of its own; with the caption on every chunk of
    the page, the search can tell the two tables apart (DAR-651).
    """
    return "[" + " · ".join([title, f"p.{page}", "; ".join(names)]) + "]"


def section_headings(text: str) -> List[str]:
    """Numbered section headings in a chunk, in order."""
    return [" ".join(m.group(1).split()) for m in _SECTION_HEADING.finditer(text)]


def chunk_sections(texts: List[str]) -> List[Optional[str]]:
    """The section(s) each chunk of one document covers, in document order.

    A chunk belongs to the section in effect where it starts (carried over from
    earlier chunks) plus any sections that start inside it.
    """
    current: Optional[str] = None
    sections: List[Optional[str]] = []
    for text in texts:
        inside = section_headings(text)
        starts_with_heading = bool(_SECTION_HEADING.match(text.lstrip()))
        names = ([] if starts_with_heading or current is None else [current]) + inside
        names = list(dict.fromkeys(names))[:_MAX_SECTIONS]
        sections.append("; ".join(names) or None)
        if inside:
            current = inside[-1]
    return sections


def _page(metadata: Dict) -> Optional[int]:
    label = str(metadata.get("page_label", ""))
    return int(label) if label.isdigit() else None


def document_root(config: AppConfig, division: Division, document: Document,
                  documents_dir: Path = DOCUMENTS_DIR) -> Optional[Path]:
    """The folder a document is read from: its division's folder, else DATA_DIR, else None.

    The document's `file` is relative to that folder, so a chunk's `source` is the
    same file name whichever folder it came from (divisions.document_for matches on it).
    """
    for root in (documents_dir / division.id, config.data_dir):
        if (root / document.file).is_file():
            return root
    return None


def build_division(config: AppConfig, division: Division, chunk_size: int, chunk_overlap: int,
                   documents_dir: Path = DOCUMENTS_DIR, stats: Optional[List[Dict]] = None,
                   with_context: bool = True, ocr: bool = False) -> List[Dict]:
    """The division's chunks, its documents in divisions.py order.

    With `with_context`, a chunk on a page with figure or table captions gets a
    `context` line (see context_line): embedded and searched with the text, but
    kept apart from it, so the sources panel still shows the page's own text.

    Each document is read and split on its own, so `stats` (when given) gets one
    row per document with its read-and-split time: at 50+ documents the build
    time is dominated by a few long or drawing-heavy PDFs, and a per-division
    total hides which ones (docs/stress-test-50-documents.md). Splitting one
    document at a time gives the same chunks, as the splitter works page by page.
    """
    roots = {d.file: document_root(config, division, d, documents_dir) for d in division.documents}
    missing = [file for file, root in roots.items() if root is None]
    if missing:
        raise SystemExit(
            f"Division {division.id}: missing {missing} in {documents_dir / division.id} or {config.data_dir} "
            f"(run `python hosted/scripts/fetch_documents.py --division {division.id}`)"
        )
    splitter = TableAwareSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks: List[Dict] = []
    for document in division.documents:
        root = roots[document.file]
        started = time.perf_counter()
        loaded = loader.load(root, only=[root / document.file], ocr=ocr, tables=True)
        # A table that runs over a page break is joined into the first page's Document (DAR-655).
        pages = merge_continued_tables(loaded)
        lines_by_page = page_lines(loaded)
        page_captions = {_page(p.metadata): captions(p.text) for p in loaded}
        nodes = [n for n in splitter.get_nodes_from_documents(pages) if n.get_content().strip()]
        texts = [n.get_content().strip() for n in nodes]
        for node, text, section in zip(nodes, texts, chunk_sections(texts)):
            page, page_end = _page(node.metadata), None
            if node.metadata.get("page_end") and page is not None:
                # A chunk of a joined table cites the pages its own rows came from.
                page, page_end = page_span(text, lines_by_page, page, int(node.metadata["page_end"]))
            chunk = {
                "text": text,
                "source": node.metadata.get("source"),
                "page": page,
                "section": section,
                "division": division.id,
            }
            if page_end:
                chunk["page_end"] = page_end
            if with_context and page is not None and page_captions.get(page):
                chunk["context"] = context_line(document.title, page, page_captions[page])
            chunks.append(chunk)
        if stats is not None:
            stats.append({
                "division": division.id,
                "source": document.file,
                "seconds": time.perf_counter() - started,
                "pdf_pages": _pdf_pages(root / document.file),
                # The loader drops pages with no text, so a scanned page is missing here.
                "pages_with_text": len({_page(p.metadata) for p in loaded}),
                "chunks": len(nodes),
                "last_page": max((int(n.metadata.get("page_end") or _page(n.metadata) or 0) for n in nodes), default=0),
            })
    return chunks


def _pdf_pages(path: Path) -> Optional[int]:
    """The PDF's page count (None for other formats), to tell how many pages had no text."""
    if path.suffix.lower() != ".pdf":
        return None
    import pymupdf  # installed with pymupdf4llm, which the loader reads PDFs with

    with pymupdf.open(path) as pdf:
        return pdf.page_count


def text_warning(row: Dict) -> Optional[str]:
    """Why a document's text may be missing from the index, or None.

    The loader silently drops a page with no text layer, so a scanned PDF builds
    with no chunks at all and still shows in the page's document list (the NCDOT
    Work Zone Safety and Mobility Policy and the Revised Rumble Strip Guidelines,
    both scanned, in the 50-document stress test). Drawing-heavy manuals lose
    pages the same way (MUTCG Chapter 2: 26 of 48 pages had text).
    """
    if row["chunks"] == 0:
        return "no text read: a scanned PDF? It has no passages, so it can never be cited"
    total = row.get("pdf_pages")
    if total and row["pages_with_text"] < 0.8 * total:
        return f"only {row['pages_with_text']} of {total} pages have text (scanned pages or drawings?)"
    return None


def embed(embedder: Embedder, texts: List[str], reuse: Optional[IndexFile] = None) -> np.ndarray:
    """One vector per text; a text already in `reuse` (an index from the same model) keeps its vector.

    Embedding all 10,000+ chunks takes about half an hour on a laptop CPU, and a
    change to how some pages are read (captions, OCR) leaves most chunks as they were.
    """
    known: Dict[str, np.ndarray] = {}
    if reuse is not None and reuse.model == embedder.model_name:
        known = {search_text(c): v for c, v in zip(reuse.chunks, reuse.vectors)}
    missing = list(dict.fromkeys(t for t in texts if t not in known))
    if missing:
        known.update(zip(missing, embedder.passages(missing)))
    print(f"embedded {len(missing)} new chunk texts, reused {len(texts) - len(missing)}")
    return np.stack([known[t] for t in texts]).astype(np.float32)


def build(config: AppConfig, divisions: List[Division], embedder: Embedder,
          chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP,
          timings: Optional[Dict] = None, reuse: Optional[IndexFile] = None,
          with_context: bool = True, keyword: bool = True, ocr: bool = False) -> IndexFile:
    """The index of these divisions' documents.

    `timings` (when given) gets "documents" (one row per document, see
    build_division), "read_split" and "embed" in seconds, so the stress test
    (prototype.stress_test) can record where build time goes. `reuse` is an
    earlier index whose vectors are kept for unchanged chunks (see embed);
    `with_context` adds the caption context lines, `keyword` the BM25 index
    and `ocr` reads pages without a text layer with OCR (rag.loader).
    """
    chunks: List[Dict] = []
    stats: List[Dict] = []
    read_started = time.perf_counter()
    for division in divisions:
        started = time.perf_counter()
        first = len(stats)
        division_chunks = build_division(config, division, chunk_size, chunk_overlap, stats=stats,
                                         with_context=with_context, ocr=ocr)
        print(f"{division.id}: {len(division_chunks)} chunks ({time.perf_counter() - started:.0f}s to read and split)")
        # The last page of each document, for its "Pages" column in docs/source-documents/SOURCES.md.
        for row in stats[first:]:
            print(f"  {row['source']}: {row['chunks']} chunks, last page {row['last_page']}, "
                  f"{row['pages_with_text']} page(s) with text, {row['seconds']:.1f}s")
            warning = text_warning(row)
            if warning:
                print(f"  WARNING {row['source']}: {warning}")
        chunks += division_chunks
    read_split = time.perf_counter() - read_started
    started = time.perf_counter()
    vectors = embed(embedder, [search_text(chunk) for chunk in chunks], reuse)
    embed_seconds = time.perf_counter() - started
    print(f"read and split {read_split:.0f}s, embedded {len(chunks)} chunks in {embed_seconds:.0f}s")
    if timings is not None:
        timings.update(documents=stats, read_split=read_split, embed=embed_seconds)
    index = IndexFile(embedder.model_name, chunks, vectors)
    return index.with_keyword_index() if keyword else index


def compare(config: AppConfig, index: IndexFile, embedder: Embedder) -> None:
    from rag.index import make_embed_model

    reference = make_embed_model(config)
    rng = np.random.default_rng(0)
    sample = rng.choice(len(index.chunks), size=min(_COMPARE_SAMPLE, len(index.chunks)), replace=False)
    texts = [index.chunks[i]["text"] for i in sample]
    ours = embedder.passages(texts)
    theirs = np.array(reference.get_text_embedding_batch(texts), dtype=np.float32)
    passage_cos = np.sum(ours * theirs, axis=1) / np.linalg.norm(theirs, axis=1)
    query_cos = []
    for question in _COMPARE_QUESTIONS:
        theirs_q = np.array(reference.get_query_embedding(question), dtype=np.float32)
        query_cos.append(float(embedder.query(question) @ theirs_q / np.linalg.norm(theirs_q)))
    print(
        f"fastembed vs sentence-transformers ({config.embedding_model}): "
        f"{len(texts)} passages cosine min={passage_cos.min():.4f} mean={passage_cos.mean():.4f}; "
        f"{len(query_cos)} queries cosine min={min(query_cos):.4f}"
    )


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.ingest", description=__doc__.splitlines()[0])
    parser.add_argument("--division", action="append", choices=sorted(BY_ID), help="only these divisions (default: all)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"directory for chunks.json and vectors.npy (default {DEFAULT_OUT})")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE, help=f"tokens per chunk (default {CHUNK_SIZE})")
    parser.add_argument("--chunk-overlap", type=int, default=CHUNK_OVERLAP, help=f"token overlap (default {CHUNK_OVERLAP})")
    parser.add_argument("--compare", action="store_true", help="check the vectors against sentence-transformers")
    parser.add_argument("--timings", type=Path, help="also write the build's timings (per document, read/split, embed) as JSON here")
    parser.add_argument("--reuse", type=Path, help="keep the vectors of chunks unchanged since the index in this directory "
                        "(the --out directory itself works; default: embed every chunk)")
    parser.add_argument("--no-context", action="store_true", help="no caption context lines (the index as before DAR-651)")
    parser.add_argument("--no-keyword", action="store_true", help="no keyword (BM25) index")
    parser.add_argument("--ocr", action="store_true", help="OCR the PDF pages that have no text layer (needs rapidocr)")
    args = parser.parse_args(argv)

    load_dotenv()
    config = load_config()
    divisions = [BY_ID[d] for d in args.division] if args.division else list(DIVISIONS)
    embedder = Embedder()
    started = time.perf_counter()
    timings: Dict = {}
    reuse = IndexFile.load(args.reuse) if args.reuse else None
    index = build(config, divisions, embedder, args.chunk_size, args.chunk_overlap, timings, reuse=reuse,
                  with_context=not args.no_context, keyword=not args.no_keyword, ocr=args.ocr)
    index.save(args.out)
    size = sum(f.stat().st_size for f in args.out.iterdir() if f.is_file())
    total = time.perf_counter() - started
    print(
        f"{len(index.chunks)} chunks from {len({c['source'] for c in index.chunks})} file(s) "
        f"in {total:.0f}s -> {args.out} ({size / 1e6:.1f} MB)"
    )
    if args.timings:
        timings.update(total=total, index_bytes=size, chunks=len(index.chunks))
        args.timings.parent.mkdir(parents=True, exist_ok=True)
        args.timings.write_text(json.dumps(timings, indent=1), encoding="utf-8")
    if args.compare:
        compare(config, index, embedder)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
