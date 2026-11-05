"""Test retrieval on pages whose answer sits in an image, a scan or a table (DAR-651).

    py -m prototype.image_table_check pages  [--out results/pages.json]
    py -m prototype.image_table_check search [--option NAME=extracted.json ...] [--save-index NAME=DIR] [--out results/search.json]
    py -m prototype.image_table_check measure --index NAME=DIR [--index NAME=DIR ...] [--out results/measure.json]
    py -m prototype.image_table_check answers --base-url http://127.0.0.1:8000 --label NAME [--out results/answers-NAME.json]

`pages` lists the pages where the index holds under LOW_TEXT characters but the
PDF page has images or vector drawings (scanned memos, figures, text drawn as
outlines), plus the pages of the test questions, as the --pages input of
prototype/ocr_extract.py, and prints how many each document has.

`search` asks each question in eval/image_table_questions.json through the
hosted app's retrieval (vector top 40 in the division, rerank, top 5) and
records whether the expected document and the expected page are in the top 5.
It runs once on the committed index ("current") and once per --option, an
index where the pages that option re-read (ocr_extract.py output) replace those
pages' chunks: the new text is split and embedded as prototype.ingest does
(512-token table-aware chunks, the hosted embedder), so only those pages differ.
--save-index writes an option's index, for the `answers` run. An option whose
NAME ends in "+captions" also starts each chunk of a page with the page's
figure and table captions (see `patched`).

`measure` runs each --index NAME=DIR with the keyword search off and on (an
index without bm25.npz gets one built in memory) on these 15 questions and on
the 83 known-page questions of prototype.stress_test (right page of the gold
document in the top 5), one row per index and setting.

The retrieval settings come from the environment as in the hosted app
(PAGE_AGGREGATION, MAX_CHUNKS_PER_PAGE, MAX_CHUNKS_PER_DOCUMENT, RRF_K,
FUSION_WEIGHTS; see divrag.config), so `PAGE_AGGREGATION=sum py -m
prototype.image_table_check measure --index sum=hosted/index` measures that
setting under the name "sum".

`answers` posts each question to a running server's /api/ask (start it with
INDEX_DIR pointing at the index to test) and records the cited pages. The free
models' daily cap is shared, so this is one LLM call per question (more on a retry).
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from prototype import HOSTED_DIR
from prototype.ingest import CHUNK_OVERLAP, CHUNK_SIZE, captions
from prototype.stress_test import _covers, _json_or_error, _source_file
from divrag.config import bm25_parameters, retrieval_options
from divrag.divisions import DIVISIONS, DOCUMENTS_DIR
from divrag.embedder import Embedder, Reranker, model_cache_dir
from divrag.index_file import IndexFile
from divrag.retrieval import Retriever

CASES = HOSTED_DIR.parent / "eval" / "image_table_questions.json"
TOP = 5
# Under this many indexed characters a page holds at most a header or a page
# number: everything else on it is out of reach of the search.
LOW_TEXT = 50
# A page with more vector drawings than this is a figure, a chart or text drawn
# as outlines (the MUTCG chapters), not just rules and table borders.
MANY_DRAWINGS = 20

PageKey = Tuple[str, int]  # (source, page)

def load_cases() -> List[Dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


def _indexed_chars(index: IndexFile) -> Counter:
    chars: Counter = Counter()
    for chunk in index.chunks:
        chars[(chunk["division"], chunk["source"], chunk["page"])] += len(chunk["text"])
    return chars


def low_text_pages(index: IndexFile) -> List[Dict]:
    """Pages with images or many drawings but under LOW_TEXT indexed characters, in document order."""
    import pymupdf

    chars = _indexed_chars(index)
    rows = []
    for division in DIVISIONS:
        for document in division.documents:
            path = DOCUMENTS_DIR / division.id / document.file
            with pymupdf.open(path) as pdf:
                for number, page in enumerate(pdf, 1):
                    indexed = chars[(division.id, document.file, number)]
                    images, drawings = len(page.get_images()), len(page.get_drawings())
                    if indexed < LOW_TEXT and (images or drawings > MANY_DRAWINGS):
                        rows.append({"division": division.id, "source": document.file, "page": number,
                                     "indexed_chars": indexed, "images": images, "drawings": drawings})
    return rows


def pages(args: argparse.Namespace) -> int:
    index = IndexFile.load(args.index)
    rows = low_text_pages(index)
    by_document = Counter((r["division"], r["source"]) for r in rows)
    print(f"{len(rows)} low-text pages with images or drawings in {len(by_document)} documents\n")
    print("| division | document | pages |\n|---|---|---|")
    for (division, source), count in by_document.most_common():
        print(f"| {division} | {source} | {count} |")
    wanted = {(r["division"], r["source"], r["page"]) for r in rows}
    for case in load_cases():
        wanted |= {(case["division"], case["source"], p) for p in case["pages"]}
    out = [{"division": d, "source": s, "page": p} for d, s, p in sorted(wanted)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\n{len(out)} pages to re-read (with the test questions' pages) -> {args.out}")
    return 0


def patched(index: IndexFile, embedder: Embedder, extracted: List[Dict], with_captions: bool = False) -> IndexFile:
    """The index with the extracted pages' chunks replaced by chunks of their new text.

    New chunks go where the page's old ones were (after the document's earlier
    pages), so "the following chunk" still means the next text of the document,
    and they take the section in effect there. `with_captions` starts every
    chunk of a page with that page's figure/table captions it doesn't already
    hold: the TMP manual's asphalt (p. 37) and concrete (p. 38) deflection
    tables differ only in their numbers and a caption under the table, which the
    splitter puts in a chunk of its own, so the numbers can't tell which is which.
    """
    from llama_index.core import Document as LlamaDocument
    from rag import loader
    from rag.tables import TableAwareSplitter

    splitter = TableAwareSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    replaced = {(r["source"], r["page"]): r for r in extracted}
    new_chunks: Dict[PageKey, List[Dict]] = {}
    for key, row in replaced.items():
        # The cleanup rag.loader's PDF reader applies (inline HTML, U+FFFD, in-cell breaks, table cells).
        text = loader.clean_markdown_tables(loader._PDF_MARKUP.sub("", row["text"]).replace("<br>", " ")).strip()
        if not text:
            new_chunks[key] = []
            continue
        page = LlamaDocument(text=text, metadata={"source": row["source"], "page_label": str(row["page"])})
        nodes = [n for n in splitter.get_nodes_from_documents([page]) if n.get_content().strip()]
        texts = [n.get_content().strip() for n in nodes]
        if with_captions:
            names = captions(text)
            texts = [("\n".join(c for c in names if c not in t) + "\n\n" + t).strip() if names else t for t in texts]
        new_chunks[key] = [{"text": t, "source": row["source"], "page": row["page"],
                            "section": None, "division": row["division"]} for t in texts]

    chunks: List[Dict] = []
    vectors: List[np.ndarray] = []
    added: List[Dict] = []
    by_document: Dict[str, List[int]] = {}
    for i, chunk in enumerate(index.chunks):
        by_document.setdefault(chunk["source"], []).append(i)
    for source, positions in by_document.items():
        pending = sorted(p for s, p in new_chunks if s == source)
        section = None
        for i in positions:
            chunk = index.chunks[i]
            while pending and (chunk["page"] or 0) >= pending[0]:
                for new in new_chunks[(source, pending.pop(0))]:
                    new["section"] = section
                    chunks.append(new)
                    added.append(new)
                    vectors.append(None)
            if (source, chunk["page"]) in replaced:
                section = chunk["section"] or section
                continue
            section = chunk["section"] or section
            chunks.append(chunk)
            vectors.append(index.vectors[i])
        for page in pending:  # pages after the document's last indexed page
            for new in new_chunks[(source, page)]:
                new["section"] = section
                chunks.append(new)
                added.append(new)
                vectors.append(None)
    fresh = iter(embedder.passages([c["text"] for c in added])) if added else iter(())
    matrix = np.stack([v if v is not None else next(fresh) for v in vectors]).astype(np.float32)
    print(f"  replaced {len(replaced)} pages: {sum(1 for c in index.chunks if (c['source'], c['page']) in replaced)} "
          f"old chunks -> {len(added)} new")
    return IndexFile(index.model, chunks, matrix)


def check(retriever: Retriever, cases: List[Dict]) -> List[Dict]:
    rows = []
    for case in cases:
        started = time.perf_counter()
        hits = retriever.retrieve(case["question"], case["division"], k=TOP)
        ms = (time.perf_counter() - started) * 1000
        in_document = [h for h in hits if h.chunk["source"] == case["source"]]
        rank = next((i for i, h in enumerate(hits, 1)
                     if h.chunk["source"] == case["source"] and h.chunk["page"] in case["pages"]), None)
        rows.append({"id": case["id"], "right_document": bool(in_document), "page_rank": rank,
                     "top": [f"{h.chunk['source']} p.{h.chunk['page']}" for h in hits], "ms": ms})
    return rows


def _pairs(values: Optional[Sequence[str]]) -> List[Tuple[str, str]]:
    return [tuple(v.split("=", 1)) for v in values or []]


def search(args: argparse.Namespace) -> int:
    index = IndexFile.load(args.index)
    cache = model_cache_dir()
    embedder = Embedder(index.model, cache_dir=cache)
    reranker = Reranker(cache_dir=cache)
    cases = load_cases()
    save = dict(_pairs(args.save_index))
    indexes = [("current", index)]
    for name, path in _pairs(args.option):
        print(f"{name}: patching the index with {path}")
        extracted = json.loads(Path(path).read_text(encoding="utf-8"))
        indexes.append((name, patched(index, embedder, extracted, with_captions=name.endswith("+captions"))))
        if name in save:
            indexes[-1][1].save(save[name])
            print(f"  saved -> {save[name]}")
    results = {}
    for name, idx in indexes:
        retriever = Retriever(idx, embedder, reranker, **retrieval_options())
        retriever.warm_up()
        results[name] = check(retriever, cases)

    names = [n for n, _ in indexes]
    fmt = lambda r: ("page #%d" % r["page_rank"]) if r["page_rank"] else ("doc only" if r["right_document"] else "miss")
    print("\n| id | division | kind | page(s) | " + " | ".join(names) + " |")
    print("|---|---|---|---|" + "---|" * len(names))
    for i, case in enumerate(cases):
        print(f"| {case['id']} | {case['division']} | {case['kind']} | {','.join(map(str, case['pages']))} | "
              + " | ".join(fmt(results[n][i]) for n in names) + " |")
    print("\n| index | right document in top 5 | right page in top 5 | right page #1 |\n|---|---|---|---|")
    for n in names:
        rows = results[n]
        print(f"| {n} | {sum(r['right_document'] for r in rows)}/{len(rows)} | "
              f"{sum(1 for r in rows if r['page_rank'])}/{len(rows)} | {sum(1 for r in rows if r['page_rank'] == 1)}/{len(rows)} |")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


def measure(args: argparse.Namespace) -> int:
    """Each index, with and without keyword search, on the 15 questions here and the 83 known-page ones."""
    from prototype.stress_test import GOLD_SOURCE, eval_cases, hit_at_5

    cache = model_cache_dir()
    reranker = Reranker(cache_dir=cache)
    cases, known = load_cases(), eval_cases()
    options = retrieval_options()
    print(f"retrieval settings: {options}")
    results = {}
    for name, path in _pairs(args.index):
        index = IndexFile.load(path)
        if index.keyword is None:
            index.with_keyword_index(*bm25_parameters())  # an index built before bm25.npz: built here
        embedder = Embedder(index.model, cache_dir=cache)
        for keyword in (False, True):
            label = f"{name}{' + keyword' if keyword else ''}"
            retriever = Retriever(index, embedder, reranker, keyword=keyword, **options)
            retriever.warm_up()
            rows = check(retriever, cases)
            started = time.perf_counter()
            known_result = hit_at_5(retriever, known)
            known_ms = (time.perf_counter() - started) * 1000 / len(known)
            known_rows = known_result["cases"]
            results[label] = {
                "image_table": {"right_document": sum(r["right_document"] for r in rows),
                                "right_page": sum(1 for r in rows if r["page_rank"]),
                                "right_page_first": sum(1 for r in rows if r["page_rank"] == 1),
                                "cases": len(rows), "rows": rows},
                "known_pages": {"right_page": sum(1 for r in known_rows if r["rank"]),
                                "right_document": sum(1 for r in known_rows
                                                      if GOLD_SOURCE[r["division"]] in r["top_sources"]),
                                "mrr": sum(1 / r["rank"] for r in known_rows if r["rank"]) / len(known_rows),
                                "cases": len(known_rows), "ms_per_question": known_ms,
                                "by_division": known_result["by_division"], "rows": known_rows},
            }
            print(f"{label}: done", flush=True)
    print("\n| index | 15 image/table: right document | right page in top 5 | right page #1 "
          "| 83 known-page: right page in top 5 | MRR | right document | ms per question |")
    print("|---|---|---|---|---|---|---|---|")
    for label, r in results.items():
        a, b = r["image_table"], r["known_pages"]
        print(f"| {label} | {a['right_document']}/{a['cases']} | {a['right_page']}/{a['cases']} | "
              f"{a['right_page_first']}/{a['cases']} | {b['right_page']}/{b['cases']} | {b['mrr']:.3f} | "
              f"{b['right_document']}/{b['cases']} | {b['ms_per_question']:.0f} |")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


def answers(args: argparse.Namespace) -> int:
    rows = []
    for case in load_cases():
        body = json.dumps({"question": case["question"], "asker": case.get("asker", case["division"]),
                           "target": case["division"], "history": []}).encode()
        request = urllib.request.Request(args.base_url.rstrip("/") + "/api/ask", data=body,
                                         headers={"Content-Type": "application/json"})
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310 - a local server
                status, payload = response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, _json_or_error(exc.read())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            status, payload = None, {"error": f"{type(exc).__name__}: {exc}"}
        wall = time.perf_counter() - started
        cited = [{"file": _source_file(s["url"]), "page": s.get("page"), "page_end": s.get("page_end")}
                 for s in payload.get("sources", [])]
        right_document = any(c["file"] == case["source"] for c in cited)
        right_page = any(c["file"] == case["source"] and _covers(c, case["pages"]) for c in cited)
        rows.append({"id": case["id"], "status": status, "seconds": wall, "refused": payload.get("refused"),
                     "uncited": payload.get("uncited"), "model": payload.get("model"), "error": payload.get("error"),
                     "cited": cited, "right_document": right_document, "right_page": right_page,
                     "answer": payload.get("answer") or "", "expected": case["answer"]})
        print(f"  {case['id']}: {status} {wall:.1f}s refused={payload.get('refused')} "
              f"doc={right_document} page={right_page}", flush=True)
    out = args.out or Path(f"answers-{args.label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"{args.label}: right document {sum(r['right_document'] for r in rows)}/{len(rows)}, "
          f"right page {sum(r['right_page'] for r in rows)}/{len(rows)}, "
          f"refused {sum(1 for r in rows if r['refused'])} -> {out}")
    return 0


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.image_table_check", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pages")
    p.add_argument("--index", default=str(HOSTED_DIR / "index"))
    p.add_argument("--out", type=Path, default=Path("pages.json"))
    s = sub.add_parser("search")
    s.add_argument("--index", default=str(HOSTED_DIR / "index"))
    s.add_argument("--option", action="append", help="NAME=ocr_extract.py output")
    s.add_argument("--save-index", action="append", help="NAME=DIR: save that option's patched index")
    s.add_argument("--out", type=Path)
    m = sub.add_parser("measure")
    m.add_argument("--index", action="append", required=True, help="NAME=DIR: an index to measure")
    m.add_argument("--out", type=Path)
    a = sub.add_parser("answers")
    a.add_argument("--base-url", default="http://127.0.0.1:8000")
    a.add_argument("--label", required=True)
    a.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    return {"pages": pages, "search": search, "measure": measure, "answers": answers}[args.command](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
