"""Run the locked test set through the hosted pipeline and write the scored report.

    py -m evaluation.locked.run run --label NAME [--split tuning|locked|all] [--stage retrieval|answer|all]
                                    [--index DIR] [--only ID ...] [--limit N] [--env-file PATH] [--questions DIR]
    py -m evaluation.locked.run freeze      write evaluation/locked/LOCKED.sha256 over the locked items
    py -m evaluation.locked.run check       exit 1 when the locked items no longer match LOCKED.sha256
    py -m evaluation.locked.run validate    the schema checks (evaluation.locked.validate)

`run` writes docs/locked-set/<label>.json (every item's scores, the aggregates
and the run's metadata: commit, index, settings) and docs/locked-set/<label>.md
(the tables, each cell as count/n with its 95% Wilson interval). A run that
includes the locked split is also appended to docs/locked-set/RUNS.md, the
count the README's "run at release only" rule is kept by.

The retrieval stage needs no model call: the hosted Retriever ranks the asked
division's chunks exactly as /api/ask does. The answer stage runs the hosted
Answerer in-process with the app's own settings and request budget (hosted/
index.py _answer), one model call per item (two on a retry). Answers go to
evaluation/locked/results/cache.jsonl keyed by item id, the model list and the
index, so a run stopped by the free models' daily cap (DAILY_LIMIT) resumes
where it stopped; a cached answer is never asked again.
"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from evaluation import ROOT
from evaluation.run_ragas import (OPENROUTER_URL, Cache, Stop, _with_busy_waits, answer_one, config_label,
                                  find_env_file)

from . import CACHE_PATH, DOCS_DIR, HASH_FILE, LOCKED_DIR, RUNS_FILE, load_items, locked_digest
from .score import METRICS, aggregate, score_item
from .validate import validate_items

STAGES = ("retrieval", "answer", "all")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git(*args: str) -> Optional[str]:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def question_sha(item: Dict[str, Any]) -> str:
    """Ties a cached answer to the question's wording: an edited question is asked again, not served stale."""
    return hashlib.sha1(item["question"].encode("utf-8")).hexdigest()[:16]


def index_info(index_dir: Path, chunks: int) -> Dict[str, Any]:
    """Where the index came from, how big it is and a fingerprint of its chunks (part of the cache key)."""
    files = sorted(p for p in Path(index_dir).glob("*") if p.is_file())
    chunks_file = Path(index_dir) / "chunks.json"
    digest = hashlib.sha256(chunks_file.read_bytes()).hexdigest()[:12] if chunks_file.is_file() else None
    return {"path": str(index_dir), "chunks": chunks, "bytes": sum(p.stat().st_size for p in files),
            "files": [p.name for p in files], "sha256_12": digest}


class Runtime:
    """The hosted app's runtime as hosted/index.py _Runtime builds it: same index, models and settings."""

    def __init__(self, settings):
        from divrag.embedder import Embedder, Reranker, model_cache_dir
        from divrag.index_file import IndexFile
        from divrag.retrieval import Retriever

        self.settings = settings
        self.index = IndexFile.load(settings.index_dir)
        cache = model_cache_dir()
        embedder = Embedder(self.index.model, cache_dir=cache)
        reranker = Reranker(cache_dir=cache) if settings.rerank else None
        self.retriever = Retriever(self.index, embedder, reranker, candidates=settings.rerank_candidates,
                                   keyword=settings.keyword_search)
        self.retriever.warm_up()

    def answerer(self, llm):
        from divrag.answer import Answerer

        s = self.settings
        return Answerer(self.retriever, llm, top_k=s.top_k, retry_min_score=s.retry_min_score if s.retry_on_refusal else None,
                        retry_min_seconds=s.retry_min_seconds)

    def retrieval(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """The top-k ranking the answer is built from (Answerer.retrieve's first step, before the following chunks)."""
        from divrag.timing import StepTimer

        timer = StepTimer()
        hits = self.retriever.retrieve(item["question"], division=item["division"], k=self.settings.top_k, timer=timer)
        ms = timer.as_ms()
        return {"ranked": [{"source": h.chunk.get("source"), "page": h.chunk.get("page"),
                            "printed_page": h.chunk.get("printed_page"), "section": h.chunk.get("section"),
                            "score": round(float(h.score), 3)} for h in hits],
                "retrieval_ms": ms["embed"] + ms["search"] + ms["rerank"]}


def cached_answer(cache: Cache, item: Dict[str, Any], answer_config: str) -> Optional[Dict[str, Any]]:
    record = cache.answer(item["id"], answer_config)
    if record and record.get("question_sha", question_sha(item)) == question_sha(item):
        return record
    return None


async def answer_stage(runtime: Runtime, llm, answer_config: str, items: Sequence[Dict[str, Any]], cache: Cache,
                       budget: float, pause: float, max_requests: Optional[int]) -> Tuple[int, Optional[str]]:
    """Answer every uncached item; (new answers, why it stopped early or None)."""
    from divrag.llm import TOO_LONG, TOO_SLOW, LLMError

    todo = [i for i in items if cached_answer(cache, i, answer_config) is None]
    print(f"answers: {len(items) - len(todo)} cached, {len(todo)} to ask ({answer_config})", flush=True)
    done = 0
    for n, item in enumerate(todo, 1):
        if max_requests is not None and n > max_requests:
            return done, f"stopped after --max-requests {max_requests}"
        asked = {"question": item["question"], "target": item["division"], "asker": item.get("asker") or item["division"]}
        record = {"kind": "answer", "id": item["id"], "answer_config": answer_config, "question_sha": question_sha(item),
                  "at": _now()}
        try:
            record.update(await _with_busy_waits(lambda: answer_one(runtime, llm, asked, budget), item["id"]))
        except Stop as stop:
            return done, str(stop)
        except LLMError as exc:
            if exc.user_message not in (TOO_SLOW, TOO_LONG):
                print(f"  [{n}/{len(todo)}] {item['id']}: {exc.user_message} ({exc}); not cached, asked again next run",
                      flush=True)
                await asyncio.sleep(pause)
                continue
            # Too slow or too long is what a visitor would get: an outcome, kept.
            record.update({"answer": None, "error": exc.user_message, "passages": [], "timing_ms": None})
        cache.add(record)
        done += 1
        answer = record.get("answer") or {}
        state = record.get("error") or ("refused" if answer.get("refused") else "uncited" if answer.get("uncited") else "answered")
        total = (record.get("timing_ms") or {}).get("total")
        print(f"  [{n}/{len(todo)}] {item['id']}: {state}" + (f" in {total / 1000:.1f}s" if total else ""), flush=True)
        await asyncio.sleep(pause)
    return done, None


def score_rows(items: Sequence[Dict[str, Any]], retrievals: Dict[str, Dict[str, Any]],
               records: Dict[str, Optional[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    rows = []
    for item in items:
        retrieval = retrievals.get(item["id"])
        record = records.get(item["id"])
        payload = record.get("answer") if record else None
        timing = (record or {}).get("timing_ms") or {}
        row = score_item(item, retrieval["ranked"] if retrieval else None, payload,
                         seconds=timing["total"] / 1000 if timing.get("total") is not None else None,
                         error=(record or {}).get("error"))
        row["question"] = item["question"]
        row["retrieval_ms"] = retrieval["retrieval_ms"] if retrieval else None
        rows.append(row)
    return rows


def build_report(label: str, items: Sequence[Dict[str, Any]], rows: Sequence[Dict[str, Any]],
                 meta: Dict[str, Any], stopped: Optional[str]) -> Dict[str, Any]:
    return {
        "label": label, "generated_at": _now(), "run": meta,
        "coverage": {"items": len(items), "retrieval_run": sum(1 for r in rows if r.get("top") is not None),
                     "answer_run": sum(1 for r in rows if r.get("refused") is not None),
                     "errors": sum(1 for r in rows if r.get("error")), "stopped": stopped},
        "aggregates": aggregate(rows, items), "items": list(rows),
    }


def _pct(stat: Dict[str, Any]) -> str:
    if not stat or not stat["n"]:
        return "-"
    low, high = stat["ci"]
    # ASCII hyphen: the summary is also printed to Windows consoles, which mangle an en dash.
    return f"{stat['k']}/{stat['n']} ({low * 100:.0f}-{high * 100:.0f}%)"


_COLUMNS = (("right_document", "right doc"), ("hit1", "hit@1"), ("hit5", "hit@5"), ("cited_page_ok_pdf", "cited PDF page"),
            ("cited_page_ok_printed", "cited printed page"), ("value_ok", "value"), ("strict_ok", "strict"),
            ("critical", "critical"))


def _stratum_table(title: str, blocks: Dict[str, Dict[str, Any]]) -> List[str]:
    lines = [f"### {title}", "", "| stratum | items | clusters | " + " | ".join(name for _, name in _COLUMNS) + " |",
             "|---|---|---|" + "---|" * len(_COLUMNS)]
    for name, block in blocks.items():
        cells = " | ".join(_pct(block["metrics"][metric]) for metric, _ in _COLUMNS)
        lines.append(f"| {name} | {block['n']} | {block['clusters']} | {cells} |")
    return lines + [""]


def render_markdown(report: Dict[str, Any]) -> str:
    run, cov, agg = report["run"], report["coverage"], report["aggregates"]
    index = run.get("index") or {}
    lines = [f"# Locked set run: {report['label']}", "",
             f"- Generated: {report['generated_at']}",
             f"- Commit: {run.get('git_commit')}" + (" (uncommitted changes)" if run.get("git_dirty") else ""),
             f"- Index: {index.get('path')} ({index.get('chunks')} chunks, {(index.get('bytes') or 0) / 1e6:.1f} MB, "
             f"sha {index.get('sha256_12')})",
             f"- Split: {run.get('split')}; stage: {run.get('stage')}; questions: {run.get('questions')}",
             f"- Models: {', '.join(run.get('settings', {}).get('models', []))}; budget {run.get('settings', {}).get('request_budget_seconds')} s",
             f"- Coverage: {cov['items']} items; retrieval run on {cov['retrieval_run']}; answers for {cov['answer_run']}"
             + (f"; {cov['errors']} model errors" if cov["errors"] else "")
             + (f"; stopped early: {cov['stopped']}" if cov["stopped"] else ""),
             "", "Each cell is count/n with its 95% Wilson interval; n is the number of items the metric is defined for. "
             "Clusters are distinct gold document pages (the independent observations).", ""]
    ab = agg["abstention"]
    lines += ["## Abstention", "", "| | answered | refused | n |", "|---|---|---|---|",
              f"| answerable | {ab['answerable']['answered']} | {ab['answerable']['refused']} | {ab['answerable']['n']} |",
              f"| unanswerable | {ab['unanswerable']['answered']} | {ab['unanswerable']['refused']} | {ab['unanswerable']['n']} |",
              "", f"Over-refusal (answerable refused): {_pct(ab['over_refusal'])}. "
              f"False answers (unanswerable answered): {_pct(ab['false_answer'])}.", ""]
    all_block = agg["all"]
    lines += ["## All items", "", "| metric | count/n (95% Wilson) |", "|---|---|"]
    for metric in METRICS:
        stat = all_block["metrics"][metric]
        extra = f"; 0 of {stat['n']} bounds the rate below {stat['upper_if_zero'] * 100:.1f}% (one-sided 95%)" \
            if stat.get("upper_if_zero") is not None else ""
        lines.append(f"| {metric} | {_pct(stat)}{extra} |")
    lines += [f"| items / clusters | {all_block['n']} / {all_block['clusters']} |", ""]
    seconds = agg["seconds"]
    if seconds["n"]:
        lines += [f"Answer time: median {seconds['median']:.1f} s, p90 {seconds['p90']:.1f} s, max {seconds['max']:.1f} s "
                  f"(n={seconds['n']}).", ""]
    lines += ["## By stratum", ""]
    for key, title in (("split", "Split"), ("division", "Division (target)"), ("type", "Question type"),
                       ("edge_case", "Edge case"), ("asker", "Asker vs target")):
        if agg.get(key):
            lines += _stratum_table(title, agg[key])
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(report: Dict[str, Any], out_dir: Path) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / f"{report['label']}.json", out_dir / f"{report['label']}.md"
    json_path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def count_locked_run(runs_file: Path, label: str, commit: Optional[str], stage: str, items: int) -> None:
    """One more line in RUNS.md: the locked set is run at release only, and every run is on record."""
    runs_file.parent.mkdir(parents=True, exist_ok=True)
    if not runs_file.exists():
        runs_file.write_text("# Locked set runs\n\nOne line per run that included the locked split (README.md: run at "
                             "release only). Count them before claiming a result on the locked set.\n\n"
                             "| date | label | commit | stage | items |\n|---|---|---|---|---|\n", encoding="utf-8")
    with runs_file.open("a", encoding="utf-8") as out:
        out.write(f"| {_now()} | {label} | {commit or '?'} | {stage} | {items} |\n")


def _settings_record(settings) -> Dict[str, Any]:
    return {"models": list(settings.models), "temperature": settings.temperature, "reasoning": settings.reasoning,
            "rerank": settings.rerank, "keyword_search": settings.keyword_search,
            "rerank_candidates": settings.rerank_candidates, "top_k": settings.top_k,
            "request_budget_seconds": settings.request_budget_seconds, "retry_on_refusal": settings.retry_on_refusal,
            "retry_min_score": settings.retry_min_score, "retry_min_seconds": settings.retry_min_seconds}


def _load_env(env_file: Optional[str]) -> None:
    path = Path(env_file) if env_file else find_env_file()
    if path and path.is_file():
        from dotenv import load_dotenv

        load_dotenv(path, override=False)  # hosted/ never loads .env itself


async def run_command(args) -> int:
    from divrag.config import load_settings

    _load_env(args.env_file)
    if args.index:
        os.environ["INDEX_DIR"] = str(Path(args.index).resolve())
    settings = load_settings()
    questions = Path(args.questions).resolve()
    items = load_items(questions)
    errors = validate_items(items)
    if errors:
        print("\n".join(errors))
        print(f"{len(errors)} problem(s) in the question files; fix them before running")
        return 1
    items = load_items(questions, split=args.split, only=args.only, limit=args.limit)
    if not items:
        print(f"no items to run (split {args.split}) in {questions}")
        return 1
    print(f"{len(items)} items (split {args.split}) from {questions}; loading the models", flush=True)
    runtime = Runtime(settings)
    index = index_info(settings.index_dir, len(runtime.index.chunks))
    retrievals = {item["id"]: runtime.retrieval(item) for item in items}
    answer_config = f"{config_label(OPENROUTER_URL, settings.models)}@{index['sha256_12']}"
    stopped = None
    records: Dict[str, Optional[Dict[str, Any]]] = {}
    if args.stage in ("answer", "all"):
        cache = Cache(Path(args.cache))
        if not settings.openrouter_api_key:
            stopped = "no OPENROUTER_API_KEY: answers skipped"
        else:
            from divrag.llm import OpenRouterClient

            llm = OpenRouterClient(settings.openrouter_api_key, settings.models, settings.temperature, settings.reasoning)
            _, stopped = await answer_stage(runtime, llm, answer_config, items, cache, settings.request_budget_seconds,
                                            args.pause, args.max_requests)
        records = {item["id"]: cached_answer(cache, item, answer_config) for item in items}
    rows = score_rows(items, retrievals, records)
    meta = {"git_commit": _git("rev-parse", "HEAD"), "git_dirty": bool(_git("status", "--porcelain")),
            "index": index, "settings": _settings_record(settings), "split": args.split, "stage": args.stage,
            "questions": str(questions), "answer_config": answer_config, "only": args.only, "limit": args.limit}
    report = build_report(args.label, items, rows, meta, stopped)
    json_path, md_path = write_outputs(report, Path(args.out))
    if args.split in ("locked", "all") and questions == LOCKED_DIR.resolve() and any(r["split"] == "locked" for r in rows):
        count_locked_run(Path(args.runs_file), args.label, meta["git_commit"], args.stage, len(items))
    print_summary(report)
    if stopped:
        print(f"stopped early: {stopped}")
    print(f"report -> {json_path}\n       -> {md_path}")
    return 0


def print_summary(report: Dict[str, Any]) -> None:
    block = report["aggregates"]["all"]
    print(f"\n{block['n']} items, {block['clusters']} clusters")
    for metric in METRICS:
        stat = block["metrics"][metric]
        if stat["n"]:
            print(f"  {metric}: {_pct(stat)}")


def freeze_command(args) -> int:
    items = load_items(Path(args.questions))
    errors = validate_items(items)
    if errors:
        print("\n".join(errors))
        print("not frozen: fix the question files first")
        return 1
    locked = [i for i in items if i["split"] == "locked"]
    digest = locked_digest(items)
    Path(args.hash_file).write_text(f"sha256 = {digest}\nitems = {len(locked)}\nfrozen = {_now()}\n", encoding="utf-8")
    print(f"{len(locked)} locked items frozen: {digest} -> {args.hash_file}")
    return 0


def read_frozen(hash_file: Path) -> Optional[str]:
    if not Path(hash_file).is_file():
        return None
    for line in Path(hash_file).read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "sha256":
            return value.strip()
    return None


def check_command(args) -> int:
    frozen = read_frozen(Path(args.hash_file))
    if frozen is None:
        print(f"no frozen hash at {args.hash_file}: run `freeze` first")
        return 1
    try:
        items = load_items(Path(args.questions))
        current = locked_digest(items)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"the question files could not be read: {exc}")
        return 1
    if current != frozen:
        print(f"locked items changed: frozen {frozen}, now {current}")
        return 1
    print(f"locked items match {args.hash_file} ({sum(1 for i in items if i['split'] == 'locked')} items)")
    return 0


def validate_command(args) -> int:
    from .validate import main as validate_main

    return validate_main(["--questions", args.questions])


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.locked.run", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--questions", default=str(LOCKED_DIR), help="directory of question files (default: evaluation/locked)")

    r = sub.add_parser("run", help="run the items and write docs/locked-set/<label>.{json,md}")
    r.add_argument("--label", required=True)
    r.add_argument("--split", choices=("tuning", "locked", "all"), default="tuning",
                   help="tuning (default): the split to tune on; locked: release runs only, each one counted")
    r.add_argument("--stage", choices=STAGES, default="all", help="retrieval: no model calls; answer/all: answers too")
    r.add_argument("--index", help="index directory (default: INDEX_DIR or hosted/index)")
    r.add_argument("--only", nargs="*", help="item ids")
    r.add_argument("--limit", type=int, help="only the first N items")
    r.add_argument("--env-file", help="default: the repo's .env (found above a git worktree too)")
    r.add_argument("--cache", default=str(CACHE_PATH))
    r.add_argument("--out", default=str(DOCS_DIR), help="where <label>.json and <label>.md go")
    r.add_argument("--runs-file", default=str(RUNS_FILE))
    r.add_argument("--pause", type=float, default=2.0, help="seconds between model calls, to pace a shared free quota")
    r.add_argument("--max-requests", type=int, help="stop the answer stage after this many new questions")
    common(r)
    f = sub.add_parser("freeze", help="write the hash of the locked items")
    f.add_argument("--hash-file", default=str(HASH_FILE))
    common(f)
    c = sub.add_parser("check", help="exit 1 when the locked items differ from the frozen hash")
    c.add_argument("--hash-file", default=str(HASH_FILE))
    common(c)
    v = sub.add_parser("validate", help="check the question files against the schema")
    common(v)
    argv = list(argv) if argv is not None else sys.argv[1:]
    # The plan's one command is `py -m evaluation.locked.run --label NAME ...`: no subcommand means run.
    if argv and argv[0].startswith("--") and argv[0] not in ("--help",):
        argv = ["run", *argv]
    args = parser.parse_args(argv)
    if args.command == "run":
        return asyncio.run(run_command(args))
    return {"freeze": freeze_command, "check": check_command, "validate": validate_command}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
