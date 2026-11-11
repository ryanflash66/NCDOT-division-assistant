"""The edge-case coverage matrix of the held-out set, as a Markdown table (docs/redo-methods.md section 7).

    py -m evaluation.heldout.matrix [--report docs/heldout-set/LABEL.json] [--questions DIR]

Counted from the question files, so it never needs a hand merge of tags.
Without --report the table shows coverage only; with one it adds each row's
results on the locked split, as count/n with the 95% Wilson interval.
A case is covered with 8 or more locked items, thin with 1 to 7, not covered
with none (the bar the research note sets for a must-pass row).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from evaluation.locked import load_items
from evaluation.locked.score import wilson

from . import EDGE_CASES, HELDOUT_DIR

COVERED = 8


def _cell(rows: Sequence[Dict[str, Any]], metric: str) -> str:
    defined = [r[metric] for r in rows if r.get(metric) is not None]
    if not defined:
        return ""
    k, n = sum(1 for v in defined if v), len(defined)
    low, high = wilson(k, n)
    return f"{k}/{n} ({low * 100:.0f}–{high * 100:.0f}%)"


def _refused(rows: Sequence[Dict[str, Any]]) -> str:
    """Must-refuse items of the row that were refused, as count/n with its interval."""
    ran = [r for r in rows if not r["answerable"] and r.get("refused") is not None]
    if not ran:
        return ""
    k, n = sum(1 for r in ran if r["refused"]), len(ran)
    low, high = wilson(k, n)
    return f"refused {k}/{n} ({low * 100:.0f}–{high * 100:.0f}%)"


def matrix(items: Sequence[Dict[str, Any]], report: Optional[Dict[str, Any]] = None) -> List[str]:
    scored = {r["id"]: r for r in (report or {}).get("items", [])}
    head = "| # | edge case | items | locked | status |"
    rule = "|---|---|---|---|---|"
    if report:
        head = "| # | edge case | items | locked | value right | value and page right | must-refuse items | clarify | status |"
        rule = "|---|---|---|---|---|---|---|---|---|"
    lines = [head, rule]
    for tag, (number, name) in EDGE_CASES.items():
        tagged = [i for i in items if tag in (i.get("edge_cases") or [])]
        locked = [i for i in tagged if i["split"] == "locked"]
        status = "covered" if len(locked) >= COVERED else "thin" if locked else "not covered"
        cells = [str(number or "—"), name, str(len(tagged)), str(len(locked))]
        if report:
            rows = [scored[i["id"]] for i in locked if i["id"] in scored]
            cells += [_cell(rows, "value_ok"), _cell(rows, "strict_ok"), _refused(rows), _cell(rows, "clarify_ok")]
        lines.append("| " + " | ".join(cells + [status]) + " |")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.heldout.matrix", description=__doc__.splitlines()[0])
    parser.add_argument("--questions", default=str(HELDOUT_DIR))
    parser.add_argument("--report", help="a run's JSON report, to add the locked split's results per row")
    args = parser.parse_args(argv)
    items = load_items(Path(args.questions))
    report = json.loads(Path(args.report).read_text(encoding="utf-8")) if args.report else None
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(matrix(items, report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
