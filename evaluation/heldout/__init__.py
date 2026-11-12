"""The held-out test set (DAR-661, DAR-718): fresh questions, written blind to the locked set's misses.

    py -m evaluation.heldout.run run --label NAME --split locked [--stage retrieval|answer|all]
    py -m evaluation.heldout.run freeze | check | validate

The locked set (evaluation/locked/) stopped being a clean test when its misses
were read to design the citation fix (decision log D17). This set replaces it
for after-numbers. It shares the locked set's schema, split rule, scorer and
runner; what differs is here: its own directory, hash file and run log, gold
pages that no older test set uses, and one fixed list of edge-case tags (the
locked files spell the same case several ways, which made the coverage matrix
a hand merge).
"""

from pathlib import Path
from typing import Any, Dict, Iterable, List

from evaluation import ROOT

HELDOUT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = HELDOUT_DIR / "results"  # gitignored: the answer cache
CACHE_PATH = RESULTS_DIR / "cache.jsonl"
HASH_FILE = HELDOUT_DIR / "HELDOUT.sha256"
DOCS_DIR = ROOT / "docs" / "heldout-set"
RUNS_FILE = DOCS_DIR / "RUNS.md"

# The 32 rows of the edge-case matrix (.handoff/redo-nov4/C-eval-edgecases.md section 9a, numbered as
# in docs/redo-methods.md section 7), one tag each, plus table_id. An item may carry several.
EDGE_CASES: Dict[str, tuple] = {
    "printed_vs_pdf": (1, "printed page differs from PDF page"),
    "chapter_page": (2, "chapter page numbers (\"5-13\")"),
    "appendix_page": (3, "appendix page numbers (\"A-4\")"),
    "near_identical": (4, "near-identical tables or pages"),
    "not_first_row_col": (5, "value not in the first row or column"),
    "multipage_table": (6, "table split over pages"),
    "merged_header": (7, "merged or multi-row headers"),
    "rotated": (8, "rotated or landscape page"),
    "scan": (9, "scanned page"),
    "degraded_scan": (10, "degraded scan (skew, stamps)"),
    "footnote": (11, "footnote or table note changes the value"),
    "units": (12, "units"),
    "range_threshold": (13, "ranges and thresholds"),
    "conditional": (14, "conditional rules"),
    "cross_reference": (15, "cross-reference (\"see Table 4\")"),
    "two_pages": (16, "answer needs two pages"),
    "conflicting_documents": (17, "documents that give different values"),
    "superseded": (18, "superseded edition"),
    "multi_column": (19, "multi-column reading order"),
    "symbols": (20, "symbols and equations"),
    "figure": (21, "figure or drawing callouts"),
    "form": (22, "forms and checklists"),
    "out_of_scope": (23, "out of scope (another state, another topic)"),
    "not_in_documents": (24, "in scope but not in the documents"),
    "false_premise": (25, "false premise"),
    "precision": (26, "numeric precision"),
    "rephrased": (27, "rephrased question"),
    "duplicate_section": (28, "same section in two divisions"),
    "toc_decoy": (29, "table-of-contents decoy"),
    "list_page_break": (30, "list that runs over a page break"),
    "missing_variable": (31, "question missing a needed variable"),
    "revision_marks": (32, "revision marks, \"reserved\""),
    "table_id": (None, "table or figure number named in the question"),
}


def tag_errors(items: Iterable[Dict[str, Any]]) -> List[str]:
    """Items whose edge_cases use a tag outside EDGE_CASES, as "file:id: ..." lines."""
    errors = []
    for item in items:
        unknown = [tag for tag in item.get("edge_cases") or [] if tag not in EDGE_CASES]
        if unknown:
            errors.append(f"{item.get('_file', '?')}:{item.get('id')}: edge_cases {unknown} are not in "
                          f"evaluation.heldout.EDGE_CASES")
    return errors
