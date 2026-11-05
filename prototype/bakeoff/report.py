"""Score every bake-off candidate and write the tables of docs/extraction-bakeoff.md (DAR-656).

    py -m prototype.bakeoff.report --out <dir used by run.py> [--doc docs/extraction-bakeoff.md]

Reads <dir>/<label>.jsonl and .meta.json for every candidate run, the text
layer (<dir>/textlayer.jsonl) as the reference, prototype/bakeoff/pages.json and
the hand-checked cells in prototype/bakeoff/cells.json. Writes
docs/extraction-bakeoff/results.json (every number, per candidate and per page
kind) and replaces the text between the `<!-- report:... -->` markers in the
doc, so the tables there always come from the last run; the prose around them
(recommendation, routing) is written by hand.
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from prototype.bakeoff import measure

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CORPUS_PAGES = 5924  # pages in the 60 indexed PDFs (corpus audit)
MIN_TEXT = 50        # pages with fewer text-layer characters have no reference to compare with

# Licence and how each candidate runs; sizes and speeds come from the run itself.
LICENCES = {
    "textlayer": "AGPL-3.0 (PyMuPDF)",
    "pymupdf4llm": "AGPL-3.0 (PyMuPDF, pymupdf4llm); RapidOCR Apache-2.0",
    "docling": "MIT (code); models Apache-2.0 / CDLA",
    "mineru": "MinerU Open Source License (Apache-2.0 + attribution, 100M MAU / USD 20M revenue cap)",
}
ORDER = ["textlayer", "pymupdf4llm", "docling", "mineru"]
START, END = "<!-- report:start -->", "<!-- report:end -->"


def _jsonl(path: Path) -> Dict[str, Dict]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["id"]] = row
    return rows


def _ratio(num: float, den: float) -> Optional[float]:
    return round(num / den, 3) if den else None


def score_candidate(label: str, rows: Dict[str, Dict], reference: Dict[str, Dict], pages: List[Dict],
                    cells: List[Dict]) -> Dict:
    by_id = {p["id"]: p for p in pages}
    read = [r for r in rows.values() if not r.get("error")]
    seconds = [r["seconds"] for r in read]
    cpu = [r["cpu_seconds"] for r in read if r.get("cpu_seconds") is not None]
    agg = defaultdict(float)
    kinds: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    fragments: List[float] = []
    for page_id, row in rows.items():
        page = by_id.get(page_id)
        if page is None:
            continue
        text = measure.strip_images(row.get("text") or "")
        ref = (reference.get(page_id) or {}).get("text") or ""
        kind = kinds[page["kind"]]
        kind["pages"] += 1
        if not row.get("error"):
            kind["read"] += 1
            kind["seconds"] += row["seconds"]
        found_tables = measure.tables(text)
        for t in found_tables:
            f = measure.header_fragmentation(t["header"])
            if f is not None:
                fragments.append(f)
        if page["audit"]["nt"] > 0:
            agg["table_pages"] += 1
            agg["table_pages_found"] += bool(found_tables)
        if len(ref.strip()) >= MIN_TEXT:
            ref_n, got_n = measure.numbers(ref), measure.numbers(text)
            overlap = measure.multiset_overlap(ref_n, got_n)
            agg["num_ref"] += sum(ref_n.values())
            agg["num_got"] += sum(got_n.values())
            agg["num_hit"] += overlap
            kind["num_ref"] += sum(ref_n.values())
            kind["num_hit"] += overlap
            ref_u, got_u = measure.units(ref), measure.units(text)
            agg["unit_ref"] += sum(ref_u.values())
            agg["unit_hit"] += measure.multiset_overlap(ref_u, got_u)
            if measure.captions(ref) and found_tables:
                agg["caption_pages"] += 1
                agg["caption_attached"] += bool(measure.caption_attached(text))
        else:
            agg["no_text_pages"] += 1
            agg["no_text_read"] += len(text.strip()) >= 100
            agg["no_text_numbers"] += sum(measure.numbers(text).values())
    cell_rows = []
    for cell in cells:
        row = rows.get(cell["id"])
        ok = bool(row) and measure.cell_found(measure.strip_images(row.get("text") or ""), cell["value"],
                                              cell.get("row_label"),
                                              cell.get("column"))
        cell_rows.append({"id": cell["id"], "value": cell["value"], "row_label": cell.get("row_label"), "ok": ok,
                          "read": bool(row)})
    offset = [c for c, cell in zip(cell_rows, cells) if cell["value"] == "Offset (ft)"]
    return {
        "label": label,
        "pages": len(rows), "errors": len(rows) - len(read),
        "seconds_mean": round(statistics.mean(seconds), 2) if seconds else None,
        "seconds_median": round(statistics.median(seconds), 2) if seconds else None,
        "cpu_seconds_mean": round(statistics.mean(cpu), 2) if cpu else None,
        "corpus_hours": round(statistics.mean(seconds) * CORPUS_PAGES / 3600, 1) if seconds else None,
        "number_recall": _ratio(agg["num_hit"], agg["num_ref"]),
        "number_precision": _ratio(agg["num_hit"], agg["num_got"]),
        "unit_recall": _ratio(agg["unit_hit"], agg["unit_ref"]),
        "table_pages_found": f"{int(agg['table_pages_found'])}/{int(agg['table_pages'])}",
        "header_fragmentation": round(statistics.mean(fragments), 3) if fragments else None,
        "caption_attached": f"{int(agg['caption_attached'])}/{int(agg['caption_pages'])}",
        "no_text_read": f"{int(agg['no_text_read'])}/{int(agg['no_text_pages'])}",
        "no_text_numbers": int(agg["no_text_numbers"]),
        # Out of the cells on pages this candidate read (all of them, except for a timing sample).
        "cells_ok": f"{sum(c['ok'] for c in cell_rows)}/{sum(c['read'] for c in cell_rows)}",
        "offset_ft_verbatim": f"{sum(c['ok'] for c in offset)}/{sum(c['read'] for c in offset)}",
        "cells": cell_rows,
        "by_kind": {k: {"pages": int(v["pages"]),
                        "seconds_mean": round(v["seconds"] / v["read"], 2) if v["read"] else None,
                        "number_recall": _ratio(v["num_hit"], v["num_ref"])} for k, v in sorted(kinds.items())},
    }


def _fmt(value) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _model_mb(meta: Dict) -> float:
    return round(sum((meta.get("model_cache_mb") or {}).values()), 0)


def tables_markdown(results: List[Dict], metas: Dict[str, Dict], n_pages: int, n_cells: int,
                    subsets: Sequence[Dict] = ()) -> str:
    lines = [
        f"Pages: {n_pages} (prototype/bakeoff/pages.json). Cells: {n_cells} hand-checked (prototype/bakeoff/cells.json).",
        "",
        "| Candidate | Pages read | Cells right | \"Offset (ft)\" verbatim | Numbers vs text layer (recall / precision) "
        "| Units kept | Table found on table pages | Caption next to table | Header fragmentation | No-text pages read "
        "| s/page (mean / median) | CPU s/page | Corpus hours | Install MB + models MB | Licence |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        meta = metas.get(r["label"], {})
        candidate = meta.get("candidate", r["label"])
        versions = ", ".join(f"{k} {v}" for k, v in (meta.get("versions") or {}).items())
        lines.append(
            f"| {r['label']} ({versions}) | {r['pages'] - r['errors']}/{r['pages']} | {r['cells_ok']} "
            f"| {r['offset_ft_verbatim']} | {_fmt(r['number_recall'])} / {_fmt(r['number_precision'])} "
            f"| {_fmt(r['unit_recall'])} | {r['table_pages_found']} | {r['caption_attached']} "
            f"| {_fmt(r['header_fragmentation'])} | {r['no_text_read']} "
            f"| {_fmt(r['seconds_mean'])} / {_fmt(r['seconds_median'])} | {_fmt(r['cpu_seconds_mean'])} "
            f"| {_fmt(r['corpus_hours'])} "
            f"| {_fmt(meta.get('install_mb'))} + {_fmt(_model_mb(meta))} | {LICENCES.get(candidate, '')} |"
        )
    kinds = sorted({k for r in results for k in r["by_kind"]})
    lines += ["", "Number recall against the text layer and seconds per page, by page kind:", "",
              "| Kind | Pages | " + " | ".join(r["label"] for r in results) + " |",
              "|---|---|" + "---|" * len(results)]
    for kind in kinds:
        cells = []
        pages = 0
        for r in results:
            k = r["by_kind"].get(kind)
            pages = max(pages, k["pages"] if k else 0)
            cells.append(f"{_fmt(k['number_recall'])} · {_fmt(k['seconds_mean'])} s" if k else "–")
        lines.append(f"| {kind} | {pages} | " + " | ".join(cells) + " |")
    lines += ["", "Hand-checked cells (✓ read right, ✗ not):", "",
              "| Page | Row | Value | " + " | ".join(r["label"] for r in results) + " |",
              "|---|---|---|" + "---|" * len(results)]
    for i, cell in enumerate(results[0]["cells"] if results else []):
        marks = [("✓" if r["cells"][i]["ok"] else "✗") if r["cells"][i]["read"] else "–" for r in results]
        lines.append(f"| {cell['id']} | {cell['row_label'] or '(header)'} | {cell['value']} | " + " | ".join(marks) + " |")
    for subset in subsets:
        lines += ["", f"On the {subset['pages']} pages {subset['label']} read (a timing sample: --sample "
                  "picks pages spread over the list, and a stopped run keeps the first ones), all candidates:", "",
                  "| Candidate | Cells right | Numbers recall / precision | Units kept | s/page | CPU s/page |",
                  "|---|---|---|---|---|---|"]
        for r in subset["results"]:
            lines.append(f"| {r['label']} | {r['cells_ok']} | {_fmt(r['number_recall'])} / "
                         f"{_fmt(r['number_precision'])} | {_fmt(r['unit_recall'])} | {_fmt(r['seconds_mean'])} "
                         f"| {_fmt(r['cpu_seconds_mean'])} |")
    lines += ["", "Load and warm-up (first page, models loaded): "
              + "; ".join(f"{label} {m.get('load_seconds')} s + {m.get('warmup_seconds')} s"
                          for label, m in metas.items()) + "."]
    return "\n".join(lines)


def write_doc(doc: Path, body: str) -> None:
    block = f"{START}\n{body}\n{END}"
    if doc.exists():
        text = doc.read_text(encoding="utf-8")
        if START in text and END in text:
            head, rest = text.split(START, 1)
            _, tail = rest.split(END, 1)
            doc.write_text(head + block + tail, encoding="utf-8")
            return
        doc.write_text(text.rstrip() + "\n\n" + block + "\n", encoding="utf-8")
        return
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(f"# Extraction bake-off (DAR-656)\n\n{block}\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="the folder run.py wrote to")
    parser.add_argument("--pages", type=Path, default=HERE / "pages.json")
    parser.add_argument("--cells", type=Path, default=HERE / "cells.json")
    parser.add_argument("--doc", type=Path, default=REPO / "docs" / "extraction-bakeoff.md")
    parser.add_argument("--results", type=Path, default=REPO / "docs" / "extraction-bakeoff" / "results.json")
    args = parser.parse_args(argv)

    pages = json.loads(args.pages.read_text(encoding="utf-8"))
    cells = json.loads(args.cells.read_text(encoding="utf-8"))["cells"]
    reference = _jsonl(args.out / "textlayer.jsonl")
    runs = {p.stem: _jsonl(p) for p in args.out.glob("*.jsonl")}
    # Tool order as in ORDER; a run on a timing sample only goes after the full runs.
    labels = sorted(runs, key=lambda s: (len(runs[s]) < len(pages),
                                         ORDER.index(s.split("-")[0]) if s.split("-")[0] in ORDER else 99, s))
    results, metas = [], {}
    for label in labels:
        meta_path = args.out / f"{label}.meta.json"
        metas[label] = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        results.append(score_candidate(label, runs[label], reference, pages, cells))
    # A candidate timed on a sample only is also compared with the others on those same pages.
    subsets = []
    for label, rows in runs.items():
        if len(rows) < len(pages):
            ids = set(rows)
            subsets.append({"label": label, "pages": len(ids), "results": [
                score_candidate(other, {k: v for k, v in runs[other].items() if k in ids}, reference,
                                [p for p in pages if p["id"] in ids], [c for c in cells if c["id"] in ids])
                for other in labels]})
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps({"results": results, "subsets": subsets, "meta": metas}, indent=1,
                                       ensure_ascii=False) + "\n", encoding="utf-8")
    write_doc(args.doc, tables_markdown(results, metas, len(pages), len(cells), subsets))
    for r in results:
        print(f"{r['label']:>16}: pages {r['pages']}, cells {r['cells_ok']}, numbers {r['number_recall']}/"
              f"{r['number_precision']}, units {r['unit_recall']}, captions {r['caption_attached']}, "
              f"no-text {r['no_text_read']}, {r['seconds_mean']} s/page")
    print("->", args.results, "and", args.doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
