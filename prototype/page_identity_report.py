"""How well each document's printed page numbers are read (rag.pages, DAR-654).

    py -m prototype.page_identity_report [--division ID ...] [--out docs/page-identity-report.json]

For every PDF of the chosen divisions (read from where prototype.ingest reads
them, plus any other PDF in the division's folder, marked "indexed": false) it
writes one row: pages, how many have a PDF page label, how many have a
printed number, how many printed numbers differ from the PDF page index, where
the numbers came from (label, footer, header) and five sample pages (first,
quarter points, last) as [pdf_index, label, printed]; plus the totals. The
committed docs/page-identity-report.json is this over the 60 documents;
docs/page-identity.md reads it.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

from prototype import HOSTED_DIR  # noqa: F401  (puts hosted/ on sys.path)
from prototype.ingest import document_root
from divrag.divisions import BY_ID, DIVISIONS, DOCUMENTS_DIR, Division  # noqa: I001
from rag import pages
from rag.config import AppConfig, load_config

DEFAULT_OUT = HOSTED_DIR.parent / "docs" / "page-identity-report.json"
SAMPLES = 5


def document_report(path: Path) -> Dict:
    identities = pages.document_identities(path)
    n = len(identities)
    sample_at = sorted({round(k * (n - 1) / (SAMPLES - 1)) for k in range(SAMPLES)}) if n else []
    return {
        "pages": n,
        "labelled": sum(1 for i in identities if i.pdf_label),
        "printed": sum(1 for i in identities if i.printed),
        "printed_differs": sum(1 for i in identities if i.printed and i.printed != str(i.pdf_index)),
        "sources": dict(Counter(i.source for i in identities if i.source)),
        "samples": [[identities[k].pdf_index, identities[k].pdf_label, identities[k].printed] for k in sample_at],
    }


def report(config: AppConfig, divisions: List[Division], documents_dir: Path = DOCUMENTS_DIR) -> Dict:
    rows: Dict[str, Dict] = {}
    for division in divisions:
        for document in division.documents:
            if not document.file.lower().endswith(".pdf"):
                continue
            root = document_root(config, division, document, documents_dir)
            if root is None:
                print(f"missing: {division.id}/{document.file}", file=sys.stderr)
                continue
            rows[f"{division.id}/{document.file}"] = {"indexed": True, **document_report(root / document.file)}
        # PDFs fetched into the division's folder but not (or no longer) in divisions.py, so the
        # report covers every file the corpus audit covers (60, two of them not indexed).
        folder = documents_dir / division.id
        for path in sorted(folder.glob("*.pdf")) if folder.is_dir() else []:
            rows.setdefault(f"{division.id}/{path.name}", {"indexed": False, **document_report(path)})
    totals = {
        "documents": len(rows),
        "indexed": sum(1 for r in rows.values() if r["indexed"]),
        "pages": sum(r["pages"] for r in rows.values()),
        "labelled": sum(r["labelled"] for r in rows.values()),
        "printed": sum(r["printed"] for r in rows.values()),
        "printed_differs": sum(r["printed_differs"] for r in rows.values()),
        "sources": dict(sum((Counter(r["sources"]) for r in rows.values()), Counter())),
        "documents_without_printed": sorted(k for k, r in rows.items() if r["printed"] == 0),
    }
    return {"totals": totals, "documents": rows}


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.page_identity_report",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--division", action="append", choices=sorted(BY_ID), help="only these divisions (default: all)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"where to write the JSON (default {DEFAULT_OUT})")
    args = parser.parse_args(argv)

    load_dotenv()
    config = load_config()
    divisions = [BY_ID[d] for d in args.division] if args.division else list(DIVISIONS)
    result = report(config, divisions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    totals = result["totals"]
    print("| document | pages | labelled | printed | differs from index | sources |")
    print("|---|---|---|---|---|---|")
    for key, row in result["documents"].items():
        sources = ", ".join(f"{s} {n}" for s, n in sorted(row["sources"].items()))
        print(f"| {key} | {row['pages']} | {row['labelled']} | {row['printed']} | {row['printed_differs']} | {sources} |")
    print(f"\n{totals['documents']} documents, {totals['pages']} pages: {totals['labelled']} labelled, "
          f"{totals['printed']} with a printed number ({totals['printed_differs']} differing from the index), "
          f"sources {totals['sources']}; no printed number in {len(totals['documents_without_printed'])} documents "
          f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
