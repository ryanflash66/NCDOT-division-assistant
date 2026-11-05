"""Pick the bake-off's hard pages from the corpus audit, deterministically (DAR-656).

    py -m prototype.bakeoff.select_pages --audit .handoff/redo-nov4/corpus-audit.json \
        --documents hosted/documents [--out prototype/bakeoff/pages.json]

The audit (one row per PDF page of the 60 documents: characters, images,
rotated characters, size, tables found, table at top/bottom, "continued", notes)
gives the candidates for each kind of hard page; the quota per kind is
QUOTAS. Within a kind the candidates are ranked by how hard they look and then
taken round-robin over the documents, so one big manual (the 2024 Standard
Specifications has most of the rotated pages) cannot fill a kind alone. A page
is counted under the first kind that takes it; `tags` lists every kind it
qualifies for. Every gold page of the DAR-651 questions
(eval/image_table_questions.json) is added on top.

Two kinds need the PDFs, not just the audit: "drawing" counts vector drawing
commands per page, and "near_duplicate" compares the words of adjacent table
pages (the TMP manual's p.37 asphalt and p.38 concrete deflection tables are the
motivating pair: same layout, same impact angles, different numbers).
"""

import argparse
import json
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = Path(__file__).resolve().parent / "pages.json"
DEFAULT_GOLD = REPO / "eval" / "image_table_questions.json"

# Kinds in priority order (a page goes to the first kind that takes it).
QUOTAS: "OrderedDict[str, int]" = OrderedDict([
    ("rotated", 20),
    ("spanned_header", 20),
    ("multi_page", 20),
    ("scan", 15),
    ("landscape", 10),
    ("drawing", 10),
    ("near_duplicate", 5),  # pages, taken in pairs (so 6)
])

ROTATED_SHARE = 0.3       # share of a page's characters on lines with dir != (1, 0)
SCAN_MAX_CHARS = 10       # the audit's "no text" line: under 10 characters
DRAWING_MIN_PATHS = 300   # vector drawing commands on the page
DRAWING_MAX_CHARS = 1500  # more text than this and it is a text page with a figure
NEAR_DUP_MIN = 0.6        # word-set Jaccard of two adjacent table pages
_WORD = re.compile(r"[a-z]+|\d+(?:\.\d+)?")

Key = Tuple[str, int]  # ("<division>/<file>.pdf", 1-based page)


def _share(p: Dict) -> float:
    return p["rotchars"] / p["totchars"] if p["totchars"] else 0.0


def _landscape(p: Dict) -> bool:
    # A landscape sheet either is wider than tall or is a portrait page shown rotated 90/270.
    return (p["w"] > p["h"]) != (p["rot"] in (90, 270))


def rotated(audit: Dict) -> List[Tuple[float, Key]]:
    return [(-_share(p), (f, p["i"])) for f, d in audit.items() for p in d["pages"]
            if p["totchars"] >= 50 and _share(p) > ROTATED_SHARE]


def spanned_header(audit: Dict) -> List[Tuple[float, Key]]:
    # Table pages with notes: in this corpus these are the design tables with
    # two-row or merged headers and footnotes under them (the deflection tables, TODS).
    return [(-p["nt"], (f, p["i"])) for f, d in audit.items() for p in d["pages"] if p["nt"] > 0 and p["notes"]]


def multi_page(audit: Dict) -> List[Tuple[float, Key]]:
    out = []
    for f, d in audit.items():
        pages = d["pages"]
        for a, b in zip(pages, pages[1:]):
            if a["tabbot"] and b["tabtop"]:
                # A table running off the bottom of one page and starting at the top of the next.
                out.append((0.0 if b["cont"] else 1.0, (f, a["i"])))
        out += [(0.5, (f, p["i"])) for p in pages if p["cont"] and p["nt"] > 0]
    return out


def scan(audit: Dict) -> List[Tuple[float, Key]]:
    return [(-p["imgs"], (f, p["i"])) for f, d in audit.items() for p in d["pages"]
            if p["chars"] < SCAN_MAX_CHARS and p["imgs"] > 0 and not p["blank"]]


def landscape(audit: Dict) -> List[Tuple[float, Key]]:
    return [(-p["nt"], (f, p["i"])) for f, d in audit.items() for p in d["pages"]
            if _landscape(p) and p["chars"] >= SCAN_MAX_CHARS]


def drawing(audit: Dict, documents: Path) -> List[Tuple[float, Key]]:
    import pymupdf

    out = []
    for f, d in sorted(audit.items()):
        candidates = [p for p in d["pages"] if SCAN_MAX_CHARS <= p["chars"] <= DRAWING_MAX_CHARS and p["nt"] == 0]
        if not candidates:
            continue
        with pymupdf.open(documents / f) as doc:
            for p in candidates:
                paths = len(doc[p["i"] - 1].get_cdrawings())
                if paths >= DRAWING_MIN_PATHS:
                    out.append((-float(paths), (f, p["i"])))
    return out


def _words(text: str) -> set:
    return set(_WORD.findall(text.lower()))


def near_duplicate(audit: Dict, documents: Path) -> List[Tuple[float, Tuple[Key, Key]]]:
    import pymupdf

    out = []
    for f, d in sorted(audit.items()):
        pages = d["pages"]
        pairs = [(a, b) for a, b in zip(pages, pages[1:]) if a["nt"] > 0 and b["nt"] > 0
                 and a["h1"] and a["h1"] != b["h1"]]
        if not pairs:
            continue
        with pymupdf.open(documents / f) as doc:
            for a, b in pairs:
                wa, wb = _words(doc[a["i"] - 1].get_text()), _words(doc[b["i"] - 1].get_text())
                jaccard = len(wa & wb) / max(len(wa | wb), 1)
                if NEAR_DUP_MIN <= jaccard < 1.0:
                    # Both pages of the pair go in, so the caption test can tell them apart.
                    out.append((-jaccard, ((f, a["i"]), (f, b["i"]))))
    return out


def round_robin(ranked: Iterable[Tuple[float, Key]], quota: int, taken: set) -> List[Key]:
    """Best-first per document, then one page per document in turn, until the quota."""
    by_doc: Dict[str, List[Key]] = defaultdict(list)
    for _, key in sorted(ranked, key=lambda r: (r[0], r[1])):
        if key not in taken and key not in by_doc[key[0]]:
            by_doc[key[0]].append(key)
    picked: List[Key] = []
    while len(picked) < quota and any(by_doc.values()):
        for doc in sorted(by_doc):
            if by_doc[doc] and len(picked) < quota:
                picked.append(by_doc[doc].pop(0))
    return picked


def round_robin_pairs(ranked: Iterable[Tuple[float, Tuple[Key, Key]]], quota: int, taken: set) -> List[Key]:
    """As round_robin, a whole pair at a time: a pair with a page already taken (by an
    earlier kind or another pair) is skipped, so the pages always come in true pairs and
    an odd quota rounds up to the next pair."""
    by_doc: Dict[str, List[Tuple[Key, Key]]] = defaultdict(list)
    for _, pair in sorted(ranked, key=lambda r: (r[0], r[1])):
        by_doc[pair[0][0]].append(pair)
    picked: List[Key] = []
    while len(picked) < quota and any(by_doc.values()):
        for doc in sorted(by_doc):
            while by_doc[doc] and len(picked) < quota:
                a, b = by_doc[doc].pop(0)
                if not ({a, b} & (taken | set(picked))):
                    picked += [a, b]
                    break
    return picked


def gold_pages(path: Path) -> List[Tuple[Key, str]]:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    return [((f"{c['division']}/{c['source']}", int(page)), c["id"]) for c in cases for page in c["pages"]]


def select(audit: Dict, documents: Path, gold: Sequence[Tuple[Key, str]]) -> List[Dict]:
    finders: Dict[str, Callable[[], List]] = {
        "rotated": lambda: rotated(audit),
        "spanned_header": lambda: spanned_header(audit),
        "multi_page": lambda: multi_page(audit),
        "scan": lambda: scan(audit),
        "landscape": lambda: landscape(audit),
        "drawing": lambda: drawing(audit, documents),
        "near_duplicate": lambda: near_duplicate(audit, documents),
    }
    candidates = {kind: finders[kind]() for kind in QUOTAS}
    tags: Dict[Key, List[str]] = defaultdict(list)
    for kind, ranked in candidates.items():
        for _, unit in ranked:
            for key in (unit if kind == "near_duplicate" else (unit,)):
                if kind not in tags[key]:
                    tags[key].append(kind)

    rows: "OrderedDict[Key, Dict]" = OrderedDict()
    for kind, quota in QUOTAS.items():
        pick = round_robin_pairs if kind == "near_duplicate" else round_robin
        for key in pick(candidates[kind], quota, set(rows)):
            rows[key] = {"kind": kind}
    for key, case_id in gold:
        row = rows.setdefault(key, {"kind": "gold"})
        row.setdefault("gold", []).append(case_id)

    pages = {f: {p["i"]: p for p in d["pages"]} for f, d in audit.items()}
    out = []
    for (f, i), row in rows.items():
        p = pages[f][i]
        division, source = f.split("/", 1)
        out.append({
            "id": f"{f}#{i}", "division": division, "source": source, "page": i, "kind": row["kind"],
            "tags": tags.get((f, i), []), "gold": row.get("gold", []),
            "audit": {k: p[k] for k in ("chars", "imgs", "w", "h", "rot", "nt", "tabtop", "tabbot", "cont", "notes")}
                     | {"rotated_share": round(_share(p), 2)},
        })
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--audit", type=Path, default=REPO / ".handoff" / "redo-nov4" / "corpus-audit.json")
    parser.add_argument("--documents", type=Path, default=REPO / "hosted" / "documents",
                        help="folder with <division>/<file>.pdf")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    rows = select(audit, args.documents, gold_pages(args.gold))
    args.out.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["kind"]] += 1
    print(", ".join(f"{k} {v}" for k, v in counts.items()), f"= {len(rows)} pages,",
          len({r['source'] for r in rows}), "documents ->", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
