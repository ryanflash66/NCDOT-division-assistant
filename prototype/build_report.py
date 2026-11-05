"""The build report: table-quality flags and page coverage per document (DAR-655).

    py -m prototype.ingest ... --report PATH              written at the end of a build
    py -m prototype.build_report --index DIR --out PATH   from an existing index, no rebuild
    py -m prototype.build_report --index DIR --markdown   print the summary tables as Markdown

The report is one JSON file:

    {"generated", "git_commit", "settings", "index",
     "documents": [{"division", "source", "pdf_pages", "pages_with_text", "empty_text_pages",
                    "ocr_pages", "chunks", "table_chunks", "flagged": [{"page", "flags", "preview"}]}],
     "totals": {"<division>": {"chunks", "table_chunks", "flagged_chunks", "<flag>": n, ...}, "all": {...}}}

The standalone mode recomputes the flags from each chunk's text (prototype.table_quality)
and, when the PDF is in hosted/documents/<division>/, the page columns from the
PDF, so the committed index can be reported without rebuilding it. Flags
already on the chunks (an index built with this report) are kept.
"""

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from prototype import HOSTED_DIR  # noqa: F401  (puts hosted/ on sys.path)
from divrag.divisions import DOCUMENTS_DIR
from prototype.table_quality import FLAGS, chunk_flags, has_table, pdf_page_stats, preview

DEFAULT_INDEX = HOSTED_DIR / "index"
# A page whose text layer has fewer characters than this had no text to read:
# with --ocr the loader read it with OCR, otherwise it produced no chunk.
_MIN_TEXT_CHARS = 10
# The worst documents by flagged share: with fewer table chunks than this the
# share says little (one bad table in two is 50%).
_MIN_TABLES_FOR_RANKING = 5
_WORST = 20
_COUNTS = ("chunks", "table_chunks", "flagged_chunks", "flagged_structure")


def git_commit() -> Optional[str]:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
                              cwd=Path(__file__).resolve().parent).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def document_path(division: str, source: str, documents_dir: Path = DOCUMENTS_DIR) -> Optional[Path]:
    """The document's PDF under hosted/documents/<division>/, or None when it isn't there."""
    path = documents_dir / division / source
    return path if path.is_file() else None


def document_report(division: str, source: str, chunks: Sequence[Dict], pdf: Optional[Path],
                    stats: Optional[Dict] = None) -> Dict:
    """One document's row: page coverage from the PDF (when given) and the flagged chunks.

    `stats` is the ingest's per-document row (pdf_pages, pages_with_text), used
    when given; otherwise both come from the PDF and the chunks' pages. Pages
    with no chunk are `empty_text_pages`; pages with a chunk but no text layer
    were read by OCR (`ocr_pages`, null without the PDF).
    """
    pages = pdf_page_stats(pdf) if pdf is not None else {}
    chunk_pages = {c["page"] for c in chunks if c.get("page") is not None}
    tables = [c for c in chunks if c.get("kind") == "table" or has_table(c["text"])]
    pdf_pages = stats.get("pdf_pages") if stats else (len(pages) or None)
    row = {
        "division": division,
        "source": source,
        "pdf_pages": pdf_pages,
        "pages_with_text": stats.get("pages_with_text", len(chunk_pages)) if stats else len(chunk_pages),
        "empty_text_pages": [p for p in range(1, (pdf_pages or 0) + 1) if p not in chunk_pages],
        # A chunk page missing from the PDF (the file was replaced by a shorter revision) is skipped.
        "ocr_pages": [p for p in sorted(chunk_pages) if p in pages and pages[p]["chars"] < _MIN_TEXT_CHARS
                      ] if pages else None,
        "chunks": len(chunks),
        "table_chunks": len(tables),
        "flagged": [],
    }
    # Only table chunks: a prose chunk carrying ocr_low_conf would otherwise
    # count against the document's tables. The flags are always recomputed
    # (chunk_flags keeps ocr_low_conf), so a threshold change shows up here
    # without rebuilding the index.
    for chunk in tables:
        flags = chunk_flags(chunk, pages.get(chunk.get("page")))
        if flags:
            row["flagged"].append({"page": chunk.get("page"), "flags": flags, "preview": preview(chunk["text"])})
    return row


def totals(documents: Iterable[Dict]) -> Dict[str, Dict[str, int]]:
    """Per division (and "all"): chunks, table chunks, flagged chunks and a count per flag."""
    out: Dict[str, Counter] = {}
    for row in documents:
        for key in (row["division"], "all"):
            counter = out.setdefault(key, Counter())
            counter["chunks"] += row["chunks"]
            counter["table_chunks"] += row["table_chunks"]
            counter["flagged_chunks"] += len(row["flagged"])
            # no_caption alone is common (many manuals print no table numbers),
            # so this is the count of tables whose text itself was read badly.
            counter["flagged_structure"] += sum(1 for item in row["flagged"] if set(item["flags"]) - {"no_caption"})
            for item in row["flagged"]:
                for flag in item["flags"]:
                    counter[flag] += 1
    return {key: {k: counter.get(k, 0) for k in _COUNTS + FLAGS}
            for key, counter in out.items()}


def build_report(chunks: Sequence[Dict], stats: Optional[Sequence[Dict]] = None, settings: Optional[Dict] = None,
                 documents_dir: Path = DOCUMENTS_DIR, index: Optional[str] = None) -> Dict:
    """The report for these chunks, documents in index order (`stats`: the ingest's per-document rows)."""
    by_document: Dict[tuple, List[Dict]] = {}
    for chunk in chunks:
        by_document.setdefault((chunk["division"], chunk["source"]), []).append(chunk)
    rows_by_document = {(s["division"], s["source"]): s for s in stats or []}
    # A document the ingest read but got no chunks from (a scanned PDF) still gets a row.
    for key in rows_by_document:
        by_document.setdefault(key, [])
    documents = [
        document_report(division, source, doc_chunks, document_path(division, source, documents_dir),
                        rows_by_document.get((division, source)))
        for (division, source), doc_chunks in by_document.items()
    ]
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "index": index,
        "settings": settings or {},
        "documents": documents,
        "totals": totals(documents),
    }


def write_report(path: Path, chunks: Sequence[Dict], stats: Optional[Sequence[Dict]] = None,
                 settings: Optional[Dict] = None, documents_dir: Path = DOCUMENTS_DIR,
                 index: Optional[str] = None) -> Dict:
    report = build_report(chunks, stats, settings, documents_dir, index)
    _write(path, report)
    return report


def _write(path: Path, report: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _structural(row: Dict) -> int:
    """The document's table chunks flagged for more than no_caption (see totals)."""
    return sum(1 for item in row["flagged"] if set(item["flags"]) - {"no_caption"})


def worst_documents(report: Dict, limit: int = _WORST) -> List[Dict]:
    """Documents with the largest share of badly read tables (at least _MIN_TABLES_FOR_RANKING tables).

    Ranked by flags beyond no_caption: ranked by any flag, the first rows were
    documents that simply print no table numbers (bpguidebook, 68 of 68).
    """
    rows = [r for r in report["documents"] if r["table_chunks"] >= _MIN_TABLES_FOR_RANKING]
    return sorted(rows, key=lambda r: (-_structural(r) / r["table_chunks"], -_structural(r)))[:limit]


def markdown_summary(report: Dict) -> str:
    """The totals per division and the worst documents as Markdown tables, for docs/table-quality.md."""
    lines = ["| Division | Chunks | Table chunks | Flagged | Flagged beyond no_caption | " + " | ".join(FLAGS) + " |",
             "|---|---|---|---|---|" + "---|" * len(FLAGS)]
    for key, t in report["totals"].items():
        lines.append(f"| {key} | {t['chunks']} | {t['table_chunks']} | {t['flagged_chunks']} | {t['flagged_structure']} | "
                     + " | ".join(str(t[f]) for f in FLAGS) + " |")
    lines += ["", "| Document | Division | Table chunks | Flagged | Beyond no_caption | Share | Top flags |",
              "|---|---|---|---|---|---|---|"]
    for r in worst_documents(report):
        counts = Counter(f for item in r["flagged"] for f in item["flags"] if f != "no_caption")
        top = ", ".join(f"{f} {n}" for f, n in counts.most_common(3))
        share = _structural(r) / r["table_chunks"]
        lines.append(f"| {r['source']} | {r['division']} | {r['table_chunks']} | {len(r['flagged'])} | "
                     f"{_structural(r)} | {share:.0%} | {top} |")
    return "\n".join(lines)


def load_chunks(index_dir: Path) -> Dict:
    """chunks.json of an index directory (only that file: no vectors or models needed)."""
    return json.loads((index_dir / "chunks.json").read_text(encoding="utf-8"))


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.build_report", description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help=f"index directory (default {DEFAULT_INDEX})")
    parser.add_argument("--out", type=Path, help="write the report JSON here")
    parser.add_argument("--documents", type=Path, default=DOCUMENTS_DIR,
                        help=f"folder with one PDF folder per division, for the page columns (default {DOCUMENTS_DIR})")
    parser.add_argument("--markdown", action="store_true", help="print the summary tables as Markdown")
    args = parser.parse_args(argv)
    if not args.out and not args.markdown:
        parser.error("give --out PATH and/or --markdown")

    meta = load_chunks(args.index)
    settings = {"mode": "standalone", "model": meta.get("model")}
    report = build_report(meta["chunks"], settings=settings, documents_dir=args.documents, index=str(args.index))
    if args.out:
        _write(args.out, report)
    t = report["totals"].get("all", {})
    print(f"{len(report['documents'])} documents, {t.get('chunks', 0)} chunks, {t.get('table_chunks', 0)} with tables, "
          f"{t.get('flagged_chunks', 0)} flagged" + (f" -> {args.out}" if args.out else ""), file=sys.stderr)
    if args.markdown:
        print(markdown_summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
