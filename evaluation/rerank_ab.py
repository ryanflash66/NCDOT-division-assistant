"""Compare rerankers on the dev sets, retrieval stage only (DAR-657, U15).

    py -m evaluation.rerank_ab [--variant NAME ...] [--locked FILE ...] [--index DIR]
                               [--out docs/reranker-ab] [--max-download-gb 1] [--timeout-minutes 15]

Each question is searched once (vector top 40 within its division, fused with
the keyword search as the app does); every variant then reranks that same pool
of 40, so the variants differ only in the rerank. Variants:

    none        the fused order, no reranker (RERANK_MODEL=none)
    minilm-l6   the app's default, Xenova/ms-marco-MiniLM-L-6-v2, int8 file
    minilm-l12  Xenova/ms-marco-MiniLM-L-12-v2
    bge-base    BAAI/bge-reranker-base
    jina-turbo  jinaai/jina-reranker-v1-turbo-en
    text-only   minilm-l6 on the text chunks only, tables at their fused rank (RERANK_TEXT_ONLY=on)

Dev sets: the 15 image/table questions (eval/image_table_questions.json), the
83 known-page questions of prototype.stress_test, and the answerable items of
the `tuning` split of each --locked file (evaluation/locked/<division>.json).
The `locked` split is never read here: the final locked-set run picks the reranker.

A question counts as found at rank r when the r-th hit is a chunk of the gold
document on a gold page; hit@1, hit@5 and MRR (over the top 5) per set. Each
variant runs in its own process, so its peak RSS is its own, and is stopped
after --timeout-minutes. A model whose download fastembed lists above
--max-download-gb is skipped. Downloads go to MODEL_CACHE_DIR. Writes
<out>.json and <out>.md. This does not change the app's default reranker.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from prototype import HOSTED_DIR
from divrag.embedder import RERANK_MODEL_NAME

REPO = HOSTED_DIR.parent
IMAGE_TABLE_CASES = REPO / "eval" / "image_table_questions.json"
TOP = 5
POOL = 40  # retrieval.DEFAULT_CANDIDATES, the app's rerank pool

# name -> (fastembed model or None, text_only)
VARIANTS: Dict[str, Tuple[Optional[str], bool]] = {
    "none": (None, False),
    "minilm-l6": (RERANK_MODEL_NAME, False),
    "minilm-l12": ("Xenova/ms-marco-MiniLM-L-12-v2", False),
    "bge-base": ("BAAI/bge-reranker-base", False),
    "jina-turbo": ("jinaai/jina-reranker-v1-turbo-en", False),
    "text-only": (RERANK_MODEL_NAME, True),
}


def _image_table_cases() -> List[Dict]:
    cases = json.loads(IMAGE_TABLE_CASES.read_text(encoding="utf-8"))["cases"]
    return [{"set": "image_table", "id": c["id"], "division": c["division"], "question": c["question"],
             "source": c["source"], "pages": list(c["pages"])} for c in cases]


def _known_page_cases(index) -> List[Dict]:
    from prototype.stress_test import GOLD_SOURCE, eval_cases, gold_pages

    return [{"set": "known_pages", "id": c["id"], "division": c["division"], "question": c["question"],
             "source": GOLD_SOURCE[c["division"]], "pages": sorted(gold_pages(c, index))} for c in eval_cases()]


def tuning_cases(path: Path) -> List[Dict]:
    """The answerable `tuning` items of a locked test set file; the `locked` split stays unread."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [{"set": "tuning", "id": item["id"], "division": item["division"], "question": item["question"],
             "source": item["expected"]["source"], "pages": list(item["expected"]["pdf_pages"])}
            for item in data["items"]
            if item.get("split") == "tuning" and not item.get("refuse") and item.get("expected")]


def on_gold_page(chunk: Dict, case: Dict) -> bool:
    """Whether the chunk is in the gold document and covers a gold page (a chunk spanning pages covers each)."""
    if chunk.get("source") != case["source"]:
        return False
    first = chunk.get("page")
    last = chunk.get("page_end") or first
    return any(first <= p <= last for p in case["pages"]) if first is not None else False


def gold_rank(chunks: Sequence[Dict], case: Dict, top: int = TOP) -> Optional[int]:
    return next((i for i, c in enumerate(chunks[:top], 1) if on_gold_page(c, case)), None)


def summarize(rows: List[Dict]) -> Dict:
    n = len(rows)
    if not n:
        return {"cases": 0, "hit1": 0, "hit5": 0, "mrr": 0.0, "seconds_per_question": 0.0}
    ranks = [r["rank"] for r in rows]
    return {"cases": n, "hit1": sum(1 for r in ranks if r == 1), "hit5": sum(1 for r in ranks if r),
            "mrr": round(sum(1 / r for r in ranks if r) / n, 4),
            "seconds_per_question": round(sum(r["seconds"] for r in rows) / n, 4)}


def _peak_rss_mb() -> Optional[float]:
    try:
        import psutil
    except ImportError:
        return None
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None)  # Windows
    if peak is None:
        import resource  # Linux reports ru_maxrss in KB

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return round(peak / 2**20, 1)


def _folder_mb(path: Path) -> float:
    """The model's size on disk: each file once (the hub cache links snapshot files to shared blobs)."""
    if not path.is_dir():
        return 0.0
    files = {}
    for f in path.rglob("*"):
        if f.is_file():
            st = f.stat()  # follows the link to the blob
            files[(st.st_dev, st.st_ino)] = st.st_size
    return round(sum(files.values()) / 2**20, 1)


def _listed(model: str):
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return next((m for m in TextCrossEncoder._list_supported_models() if m.model == model), None)


def build_pools(index_dir: str, locked: Sequence[Path], out: Path) -> Dict:
    """Search every case once and save its pool of POOL chunk numbers (the input of every variant)."""
    from divrag.embedder import Embedder, model_cache_dir
    from divrag.index_file import IndexFile
    from divrag.retrieval import Retriever

    index = IndexFile.load(index_dir)
    if index.keyword is None:
        index.with_keyword_index()
    cases = _image_table_cases() + _known_page_cases(index)
    for path in locked:
        cases += tuning_cases(path)
    retriever = Retriever(index, Embedder(index.model, cache_dir=model_cache_dir()), None, keyword=True)
    retriever.warm_up()
    number = {id(c): i for i, c in enumerate(index.chunks)}
    started = time.perf_counter()
    for case in cases:
        case["pool"] = [number[id(h.chunk)] for h in retriever.candidates_for(case["question"], case["division"], POOL)]
    search_seconds = (time.perf_counter() - started) / max(1, len(cases))
    data = {"index": str(index_dir), "search_seconds_per_question": round(search_seconds, 4), "cases": cases}
    out.write_text(json.dumps(data), encoding="utf-8")
    return data


def run_variant(name: str, pools_file: Path, index_dir: str, result_file: Optional[Path] = None) -> Dict:
    """One variant over the saved pools (runs in its own process; see main).

    With `result_file` the rows so far are saved after each question, so a variant
    stopped at the time limit still reports the questions it finished.
    """
    from divrag.embedder import Reranker, model_cache_dir
    from divrag.index_file import Hit, IndexFile
    from divrag.retrieval import is_table, rerank, rerank_text_only

    model, text_only = VARIANTS[name]
    data = json.loads(pools_file.read_text(encoding="utf-8"))
    chunks = IndexFile.load(index_dir).chunks
    rss_before = _peak_rss_mb()
    cache = model_cache_dir()
    reranker = None
    load_seconds = 0.0
    if model:
        started = time.perf_counter()
        reranker = Reranker(model, cache_dir=cache)
        reranker.scores("warm up", ["warm up"])
        load_seconds = time.perf_counter() - started
    rows, tables_in_pool = [], 0
    for case in data["cases"]:
        hits = [Hit(float(POOL - i), chunks[n]) for i, n in enumerate(case["pool"])]
        tables_in_pool += sum(1 for h in hits if is_table(h.chunk))
        started = time.perf_counter()
        if reranker and len(hits) > 1:
            hits = rerank_text_only(reranker, case["question"], hits) if text_only else rerank(reranker, case["question"], hits)
        seconds = time.perf_counter() - started
        rows.append({"set": case["set"], "id": case["id"], "rank": gold_rank([h.chunk for h in hits], case),
                     "seconds": round(seconds, 4),
                     "top": [f"{h.chunk['source']} p.{h.chunk['page']}" for h in hits[:TOP]]})
        if result_file:
            _save(result_file, _variant_result(name, cache, load_seconds, rss_before, tables_in_pool, rows))
    return _variant_result(name, cache, load_seconds, rss_before, tables_in_pool, rows)


def _variant_result(name: str, cache: str, load_seconds: float, rss_before: Optional[float],
                    tables_in_pool: int, rows: List[Dict]) -> Dict:
    model, text_only = VARIANTS[name]
    size_mb = None
    if model:
        listed = _listed(model)
        repo = listed.sources.hf if listed else model
        size_mb = _folder_mb(Path(cache) / ("models--" + repo.replace("/", "--")))
    return {"variant": name, "model": model, "text_only": text_only, "load_seconds": round(load_seconds, 2),
            "rss_before_model_mb": rss_before, "peak_rss_mb": _peak_rss_mb(), "model_size_mb": size_mb,
            "tables_per_pool": round(tables_in_pool / max(1, len(rows)), 2), "rows": rows}


def _save(path: Path, data: Dict) -> None:
    """Write through a temporary file, so a reader never sees half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def report(results: Dict, data: Dict, sets: List[str]) -> str:
    counts = {s: sum(1 for c in data["cases"] if c["set"] == s) for s in sets}
    lines = ["# Reranker A/B on the dev sets (DAR-657)", "",
             "Retrieval stage only: each question searched once (vector top 40 in its division fused with the "
             "keyword search), then each variant reranks the same 40. Found = a chunk of the gold document on a "
             "gold page; hit@1, hit@5 and MRR over the top 5. Seconds are rerank time per question, on top of "
             f"{data['search_seconds_per_question']:.3f} s of search. Peak RSS is the variant's own process "
             "(index chunks + model). The default reranker is unchanged; the locked-set run picks.", "",
             "Sets: " + ", ".join(f"{s} ({counts[s]})" for s in sets) + ".", ""]
    partial = [f"{name} ran {r['partial']}" for name, r in results.items() if r.get("partial")]
    if partial:
        lines += ["Stopped at the time limit, scored on the questions finished: " + "; ".join(partial) + ".", ""]
    head = "| variant | " + " | ".join(f"{s} hit@1 | hit@5 | MRR" for s in sets) + " | s/question | load s | peak RSS MB | model MB |"
    lines += [head, "|" + "---|" * (1 + 3 * len(sets) + 4)]
    for name, r in results.items():
        if "skipped" in r:
            lines.append(f"| {name} | skipped: {r['skipped']} |" + " |" * (3 * len(sets) + 3))
            continue
        cells = []
        for s in sets:
            a = r["sets"][s]  # a variant stopped at the time limit may not have reached a set
            cells += [f"{a['hit1']}/{a['cases']}", f"{a['hit5']}/{a['cases']}", f"{a['mrr']:.3f}"] if a["cases"] else ["-"] * 3
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {r['all']['seconds_per_question']:.3f} | {r['load_seconds']} | "
                     f"{r['peak_rss_mb']} | {r['model_size_mb'] if r['model_size_mb'] is not None else '-'} |")
    return "\n".join(lines) + "\n"


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.rerank_ab", description=__doc__.splitlines()[0])
    parser.add_argument("--variant", action="append", choices=list(VARIANTS), help="default: all")
    parser.add_argument("--locked", action="append", type=Path, default=[], help="a locked test set file (tuning split read)")
    parser.add_argument("--index", default=str(HOSTED_DIR / "index"))
    parser.add_argument("--out", type=Path, default=REPO / "docs" / "reranker-ab")
    parser.add_argument("--max-download-gb", type=float, default=1.0)
    parser.add_argument("--timeout-minutes", type=float, default=15.0)
    parser.add_argument("--pools", type=Path, help="reuse the pools.json of an earlier run (same index and sets)")
    parser.add_argument("--reuse", action="append", default=[], metavar="NAME=FILE",
                        help="take a variant's result from an earlier run on the same pools")
    parser.add_argument("--worker", choices=list(VARIANTS), help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv[1:])

    if args.worker:
        _save(args.result, run_variant(args.worker, args.pools, args.index, args.result))
        return 0

    work = Path(tempfile.mkdtemp(prefix="rerank_ab_"))
    print(f"work dir: {work}", flush=True)
    if args.pools:
        pools, data = args.pools, json.loads(args.pools.read_text(encoding="utf-8"))
    else:
        pools = work / "pools.json"
        data = build_pools(args.index, args.locked, pools)
    reuse = dict(pair.split("=", 1) for pair in args.reuse)
    sets = [s for s in ("image_table", "known_pages", "tuning") if any(c["set"] == s for c in data["cases"])]
    print(f"pools: {len(data['cases'])} questions, {data['search_seconds_per_question']:.3f} s search each", flush=True)
    results: Dict[str, Dict] = {}
    for name in args.variant or list(VARIANTS):
        model = VARIANTS[name][0]
        result_file = Path(reuse[name]) if name in reuse else work / f"{name}.json"
        listed = _listed(model) if model else None
        if model and listed is None:
            results[name] = {"skipped": f"fastembed has no {model}"}
        elif listed is not None and listed.size_in_GB > args.max_download_gb:
            results[name] = {"skipped": f"{model} is a {listed.size_in_GB} GB download (limit {args.max_download_gb} GB)"}
        if name in results:
            print(f"{name}: {results[name]['skipped']}", flush=True)
            continue
        command = [sys.executable, "-m", "evaluation.rerank_ab", "--worker", name, "--pools", str(pools),
                   "--result", str(result_file), "--index", args.index]
        started = time.perf_counter()
        stopped = False
        try:
            if name not in reuse:
                subprocess.run(command, check=True, timeout=args.timeout_minutes * 60, cwd=REPO, env=os.environ.copy())
        except subprocess.TimeoutExpired:
            stopped = True
            if not result_file.exists():
                results[name] = {"skipped": f"stopped after {args.timeout_minutes:g} min before any question"}
        except subprocess.CalledProcessError as error:
            results[name] = {"skipped": f"failed (exit {error.returncode})"}
        if name in results:
            print(f"{name}: {results[name]['skipped']}", flush=True)
            continue
        r = json.loads(result_file.read_text(encoding="utf-8"))
        if listed is not None:  # measured here too, so a reused result gets the same measure
            from divrag.embedder import model_cache_dir

            r["model_size_mb"] = _folder_mb(Path(model_cache_dir()) / ("models--" + listed.sources.hf.replace("/", "--")))
        if stopped or len(r["rows"]) < len(data["cases"]):
            r["partial"] = f"{len(r['rows'])} of {len(data['cases'])} questions in {args.timeout_minutes:g} min"
        r["sets"] = {s: summarize([row for row in r["rows"] if row["set"] == s]) for s in sets}
        r["all"] = summarize(r["rows"])
        r["wall_seconds"] = round(time.perf_counter() - started, 1)
        results[name] = r
        print(f"{name}: " + ", ".join(f"{s} hit@5 {r['sets'][s].get('hit5', 0)}/{r['sets'][s]['cases']}" for s in sets)
              + f", {r['all']['seconds_per_question']:.3f} s/question", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"search_seconds_per_question": data["search_seconds_per_question"], "index": args.index,
               "locked_files": [str(p) for p in args.locked], "pool": POOL, "top": TOP, "variants": results}
    args.out.with_suffix(".json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    md = report(results, data, sets)
    args.out.with_suffix(".md").write_text(md, encoding="utf-8")
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
