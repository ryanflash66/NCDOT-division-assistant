"""Run the multi-page table merge rule (rag.table_merge) on the corpus audit's candidate page breaks (DAR-655).

    py -m prototype.table_merge_check [--audit corpus-audit.json] [--out results/table-merge.json] [--show FILE:PAGE ...]

A candidate is a page whose find_tables box ends in the bottom 10% of the page
(`tabbot` in the audit) followed by a page whose box starts in the top 12%
(`tabtop`): 166 breaks in the 60 documents. Each candidate's document is read
with the build's reader (rag.loader with table boxes), but only the pages
around the candidates (the Standard Specifications have 857 pages), and the
rule's decision for each break is written to --out and printed as Markdown
rows for docs/table-merge-check.md. --show prints the end of page N and the
start of page N+1 for hand-checking one break.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import pymupdf4llm

from prototype import HOSTED_DIR  # noqa: F401  (puts hosted/ on sys.path)
from divrag.divisions import DOCUMENTS_DIR
from rag import loader
from rag.table_merge import merge_decisions

DEFAULT_AUDIT = Path(r"R:\_code_\RAG-Chatbot\.handoff\redo-nov4\corpus-audit.json")
# Pages read on each side of a candidate break: enough for running heads and
# footers to repeat MIN_RUNNING_PAGES times, and for a table over a few pages to chain.
WINDOW = 3


def candidates(audit: Dict) -> List[Tuple[str, int, bool]]:
    """(audit key "<division>/<file>", page N, whether page N+1 says "continued") for every tabbot→tabtop break."""
    out = []
    for key, doc in audit.items():
        pages = {p["i"]: p for p in doc["pages"]}
        for i, page in sorted(pages.items()):
            following = pages.get(i + 1)
            if page.get("tabbot") and following and following.get("tabtop"):
                out.append((key, i, bool(following.get("cont"))))
    return out


def load_pages(key: str, numbers: List[int]):
    """The build reader's page Documents for these 1-based pages of one audited document."""
    division, file = key.split("/", 1)
    root = DOCUMENTS_DIR / division
    full = pymupdf4llm.to_markdown
    wanted = sorted({n - 1 for n in numbers})

    # pymupdf4llm reads every page unless told otherwise; the reader has no page
    # option because the build always wants the whole document.
    def windowed(path, **kwargs):
        return full(path, pages=wanted, **kwargs)

    pymupdf4llm.to_markdown = windowed
    try:
        return loader.load(root, only=[root / file], tables=True)
    finally:
        pymupdf4llm.to_markdown = full


def run(audit_path: Path) -> List[Dict]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    by_doc: Dict[str, List[Tuple[int, bool]]] = defaultdict(list)
    for key, page, cont in candidates(audit):
        by_doc[key].append((page, cont))
    rows = []
    for key, breaks in by_doc.items():
        n = audit[key]["n"]
        numbers = [p for page, _ in breaks for p in range(max(1, page - WINDOW), min(n, page + 1 + WINDOW) + 1)]
        decisions = {d.page: d for d in merge_decisions(load_pages(key, numbers))}
        for page, cont in breaks:
            d = decisions.get(page)
            rows.append({"document": key, "page": page, "next_page": page + 1, "audit_cont": cont,
                         "merged": bool(d and d.merged),
                         "reason": d.reason if d else "a page has no text after extraction",
                         "signals": d.signals if d else {}})
        print(f"{key}: {sum(r['merged'] for r in rows if r['document'] == key)}/{len(breaks)} merged", file=sys.stderr, flush=True)
    return rows


def show(key_page: str) -> None:
    key, page = key_page.rsplit(":", 1)
    page = int(page)
    docs = {int(d.metadata["page_label"]): d for d in load_pages(key, [page, page + 1])}
    print(f"===== {key} p.{page} (last lines)")
    print("\n".join(docs[page].text.rstrip().split("\n")[-12:]) if page in docs else "(no text)")
    print(f"===== p.{page + 1} (first lines)")
    print("\n".join(docs[page + 1].text.lstrip().split("\n")[:12]) if page + 1 in docs else "(no text)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--show", nargs="+", metavar="DIVISION/FILE.pdf:PAGE")
    args = parser.parse_args(argv)
    if args.show:
        for item in args.show:
            show(item)
        return 0
    rows = run(args.audit)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("| # | document | pages | audit `cont` | rule | reason |\n|---|---|---|---|---|---|")
    for n, r in enumerate(rows, 1):
        print(f"| {n} | {r['document']} | {r['page']}–{r['next_page']} | {'yes' if r['audit_cont'] else ''} | "
              f"{'merge' if r['merged'] else 'keep apart'} | {r['reason']} |")
    print(f"\n{sum(r['merged'] for r in rows)} of {len(rows)} candidate breaks merged", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
