"""The RAGAS judge on a held-out run's saved answers (DAR-650): no new answer calls.

    py -m evaluation.heldout.ragas --report docs/heldout-set/openai-site-dar738.json --dry-run
    py -m evaluation.heldout.ragas --report docs/heldout-set/openai-site-dar738.json \
        --judge-base-url https://api.openai.com/v1 --judge-models gpt-6.1-terra     # JUDGE_API_KEY
    py -m evaluation.heldout.ragas --report docs/heldout-set/openai-site-dar738.json --stage report

Published RAG systems mostly report judge-scored metrics (RAGAS faithfulness,
answer relevancy, context precision and recall), not exact value match. This
puts the held-out run on that footing next to its exact-match numbers, with
the judge, prompt, metrics and charts of evaluation/run_ragas.py.

The answers come from the held-out answer cache (evaluation/heldout/results/
cache.jsonl) for the run the report describes: the cached run whose answers
are the report's. A --site run keeps no passage text (/api/ask returns only
excerpts of the cited ones), so the passages the site's model read are
rebuilt here with the hosted Answerer on the local index: the same question
gives the same passages when the index and the retriever settings are the
site's, which is checked against the report before anything runs. A retried
answer (a refusal asked again with the next ranked passages) read the wider
set, so that is rebuilt for it. Every cited excerpt must be found in the
rebuilt passages; the run stops when more than --max-mismatch answers fail
that check.

The reference answer the judge scores context recall and precision against is
the item's gold value (expected.value, or each part of expected.all_of), not
its authoring note, which also names pages checked elsewhere. Must-refuse
items have no reference, and need no verdict once refused.

Verdicts go to their own cache (--cache), so the free judge's verdicts on the
Oct 27 test set are untouched. OpenAI calls count against the hosted app's
monthly limit as in run_ragas.py. Locked-split rules hold: the report gives
aggregates; reading a locked item's verdicts in detail makes it a development
item (evaluation/heldout/README.md).
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from evaluation import EVALUATION_DIR, ROOT
from evaluation import metrics as m
from evaluation import run_ragas as rr
from evaluation.locked import load_items
from evaluation.locked.run import index_info, question_sha

from . import CACHE_PATH, HELDOUT_DIR
# Per-item verdicts and scores go beside the answer cache, which is gitignored: only aggregates of a
# held-out run are committed (the markdown and the charts), never its items.
from . import RESULTS_DIR
# Typical judge reply for the estimate: the four verdict lists for five passages and a short answer.
TYPICAL_OUTPUT_TOKENS = 1000


def reference_of(item: Dict[str, Any]) -> Optional[str]:
    """The gold answer as text: the value (with its unit), or every part of all_of; None for must-refuse items."""
    expected = item.get("expected")
    if item.get("refuse") or not expected:
        return None
    parts = []
    for part in expected.get("all_of") or []:
        parts.append(part[0] if isinstance(part, list) else part)
    if not parts and expected.get("value") is not None:
        value, unit = str(expected["value"]), expected.get("unit")
        parts.append(f"{value} {unit}" if unit and unit not in value else value)
    return "; ".join(str(p) for p in parts) or None


def ragas_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """A held-out item in run_ragas's item shape."""
    expected = item.get("expected") or {}
    return {"id": item["id"], "question": item["question"], "target": item["division"], "asker": item.get("asker"),
            "group": item.get("type"), "answerable": not item.get("refuse"), "holdout": item.get("split") == "locked",
            "split": item.get("split"), "behaviour": item.get("behaviour"), "reference": reference_of(item),
            "gold_source": expected.get("source"), "gold_pages": expected.get("pdf_pages") or []}


def pick_answer_config(answers: Dict[str, Dict[str, Dict[str, Any]]], report_rows: Dict[str, Dict[str, Any]]) -> str:
    """The cached run whose answers are the report's: the answer config with the most identical answer texts."""
    def matches(config: str) -> int:
        texts = {qid: ((record.get("answer") or {}).get("answer")) for qid, record in answers[config].items()}
        return sum(1 for qid, row in report_rows.items() if row.get("answer") and texts.get(qid) == row["answer"])

    scored = sorted(((matches(c), c) for c in answers), reverse=True)
    if not scored or scored[0][0] < 0.95 * sum(1 for r in report_rows.values() if r.get("answer")):
        raise SystemExit("no cached run matches the report's answers: run the held-out answers first, or pass --answer-config")
    return scored[0][1]


def load_site_answers(cache_path: Path) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{answer_config: {id: record}} from the held-out answer cache, the latest record per key."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for number, line in enumerate(cache_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            # A run stopped mid-write leaves a cut-off last line (as rr.Cache): that item has no answer here.
            print(f"warning: {cache_path.name} line {number} is not valid JSON; skipped", file=sys.stderr)
            continue
        if record.get("kind") == "answer":
            out.setdefault(record["answer_config"], {})[record["id"]] = record
    return out


def answer_matches(record: Optional[Dict[str, Any]], row: Dict[str, Any]) -> bool:
    """Whether the cached answer is the one the report scored: pick_answer_config takes a run when 95% match."""
    return ((record or {}).get("answer") or {}).get("answer") == row.get("answer")


# Every setting that changes which passages the model reads. A --site run records the site's in run.site_health
# (the reranker, fusion and per-page caps as well as top_k), a local run only the first four in run.settings.
PASSAGE_SETTINGS = ("top_k", "rerank", "keyword_search", "rerank_candidates", "rerank_model", "rerank_model_file",
                    "rerank_text_only", "keyword_field", "keyword_field_boost", "keyword_id_boost", "page_aggregation",
                    "max_chunks_per_page", "max_chunks_per_document", "rrf_k", "fusion_weights", "bm25_k1", "bm25_b")
# The code that builds them, the second look after a refusal included (Answerer._second_look, with_next_page).
PASSAGE_CODE = ("hosted/divrag", "hosted/index")


def check_settings(settings, run: Dict[str, Any], index: Dict[str, Any]) -> List[str]:
    """What differs between this checkout's retrieval and the run's; the rebuilt passages are the site's only without."""
    problems = []
    if run.get("index", {}).get("sha256_12") != index["sha256_12"]:
        problems.append(f"index {index['sha256_12']} is not the run's {run.get('index', {}).get('sha256_12')}")
    ran = {**(run.get("site_health") or {}), **(run.get("settings") or {})}
    for key in PASSAGE_SETTINGS:
        local = getattr(settings, key, None)
        was = tuple(ran[key]) if isinstance(ran.get(key), list) else ran.get(key)
        if was is not None and local is not None and was != (tuple(local) if isinstance(local, list) else local):
            problems.append(f"{key} is {local} here and was {was} in the run")
    return problems


def check_code(run: Dict[str, Any]) -> List[str]:
    """Whether the retrieval code here is the run's: a --site run records the commit production was deployed from."""
    import subprocess

    commit = run.get("git_commit")
    if not commit:
        return []
    diff = subprocess.run(["git", "diff", "--quiet", commit, "--", *PASSAGE_CODE], cwd=ROOT, capture_output=True)
    if diff.returncode == 0:
        return []
    return [f"the retrieval code ({', '.join(PASSAGE_CODE)}) differs from the run's commit {commit[:12]}"
            if diff.returncode == 1 else f"can't compare the retrieval code with the run's commit {commit[:12]}"]


def cached_judge_configs(cache, answer_config: str) -> List[str]:
    """The judges that gave this run's cached verdicts, most verdicts first: what --stage report scores with."""
    counts: Dict[str, int] = {}
    for key in cache.verdicts:
        if key[1] == answer_config:
            counts[key[4]] = counts.get(key[4], 0) + 1
    return sorted(counts, key=lambda c: -counts[c])


def excerpts_found(answer: Dict[str, Any], shown: Sequence[str]) -> Tuple[int, int]:
    """(cited excerpts among `shown`, cited excerpts): `shown` are the app's excerpts of the rebuilt passages."""
    sources = [s for s in answer.get("sources") or [] if s.get("excerpt")]
    found = sum(1 for s in sources if s["excerpt"] in set(shown))
    return found, len(sources)


def rebuild_passages(answerer, item: Dict[str, Any], retried: bool) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The passages the site's model read for the item, as run_ragas records numbered as the model saw them,
    and the app's source excerpt of each passage and each merged part (a citation can name one part, narrow()).

    A retried answer read the first passages and then the second look after them
    (Answerer._retry numbers them on from the first ones).
    """
    from divrag.answer import _excerpt
    from divrag.divisions import BY_ID

    hits = answerer.retrieve(item["question"], BY_ID[item["target"]])
    shown = list(hits) + (answerer._second_look(hits) if retried else [])
    excerpts = [_excerpt(c.get("text") or "") for h in shown for c in [h.chunk, *(h.chunk.get("parts") or [])]]
    return [rr.passage_record(n, h) for n, h in enumerate(shown, 1)], excerpts


def page_retrieval(item: Dict[str, Any], top: Sequence[str], passages: Sequence[Dict[str, Any]],
                   retrieval_ms: Optional[int]) -> Dict[str, Any]:
    """run_ragas's page metrics on (document, page) pairs: page numbers repeat across a division's documents."""
    def pair(label: str) -> Tuple[str, Optional[int]]:
        source, _, page = label.rpartition(" p.")
        return source, int(page) if page.isdigit() else None

    ranked = [pair(t) for t in top]
    shown = {(p["source"], page) for p in passages for page in p["pages"]}
    gold = [(item["gold_source"], page) for page in item["gold_pages"]]
    return {"ranked_pages": [p for _, p in ranked], "retrieval_ms": retrieval_ms,
            **m.page_metrics(ranked, shown, gold)}


class _Pipe:
    """What run_ragas.report needs of its Pipeline: the index (for the header) and the embedder (answer relevancy)."""

    def __init__(self, runtime):
        self.index = runtime.index
        self.embedder = runtime.retriever.embedder


def prompt_tokens(item: Dict[str, Any], record: Dict[str, Any]) -> int:
    from divrag.spend import estimate_tokens
    from evaluation.judge import judge_messages

    messages = judge_messages(item["question"], [p["text"] for p in record["passages"]], record["answer"]["answer"],
                              item.get("reference"))
    return sum(estimate_tokens(msg["content"]) for msg in messages)


def print_estimate(todo: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]], prices: Optional[Tuple[float, float]]) -> None:
    """The judge calls this run makes and what they cost on `prices`, from the actual prompts."""
    from divrag.spend import cost_usd

    tokens = [prompt_tokens(item, record) for item, record in todo]
    total_in = sum(tokens)
    print(f"judge: {len(todo)} verdicts to ask; prompts {total_in:,} tokens in all "
          f"(median {sorted(tokens)[len(tokens) // 2] if tokens else 0:,}, max {max(tokens, default=0):,})", flush=True)
    if prices:
        typical = cost_usd(prices, total_in, TYPICAL_OUTPUT_TOKENS * len(todo))
        worst = rr.JUDGE_CALLS * cost_usd(prices, total_in, rr.JUDGE_CALL_TOKENS[1] * len(todo))
        print(f"judge cost at ${prices[0]:g}/${prices[1]:g} per million in/out: about ${typical:.2f} "
              f"({TYPICAL_OUTPUT_TOKENS} tokens out each), at most ${worst:.2f} "
              f"({rr.JUDGE_CALL_TOKENS[1]} out, every verdict asked twice)", flush=True)


def write_markdown(scores: Dict[str, Any], report_path: Path, rebuilt: Dict[str, Any], out: Path) -> None:
    """The aggregates as a short Markdown report (no per-item lines: most items are on the locked split)."""
    summary = scores["summary"]
    groups = list(summary)
    lines = [f"# RAGAS judge on {report_path.stem}", "",
             f"- Answers: {scores['answer_config']} (from `{report_path.as_posix()}`, no new answer calls)",
             f"- Judge: {scores['judge_config']}",
             f"- Coverage: {scores['coverage']['judged']}/{scores['coverage']['needing_judge']} judged"
             + (f"; stopped early: {scores['coverage']['stopped']}" if scores['coverage']['stopped'] else ""),
             f"- Passages rebuilt on the local index: {rebuilt['answers']} answers, cited excerpts found "
             f"{rebuilt['found']}/{rebuilt['cited']}, answers with a missing excerpt {rebuilt['mismatched']}, "
             f"retried answers (wider passages) {rebuilt['retried']}",
             "", "| metric | " + " | ".join(groups) + " |", "|---|" + "---|" * len(groups)]
    for key in rr.METRIC_KEYS:
        lines.append(f"| {key} | " + " | ".join(rr._fmt(summary[g][key]) for g in groups) + " |")
    lines += ["", "Means with 95% bootstrap intervals and n. Page metrics are on (document, PDF page) pairs. "
              "See evaluation/METRICS.md for the definitions.", ""]
    out.write_text("\n".join(lines), encoding="utf-8")


async def run(args) -> int:
    from divrag.config import load_settings
    from divrag.spend import SpendLedger, store_from_env
    from evaluation.locked.run import Runtime

    env_file = Path(args.env_file) if args.env_file else rr.find_env_file()
    if env_file and env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)
    report_path = Path(args.report)
    held = json.loads(report_path.read_text(encoding="utf-8"))
    report_rows = {r["id"]: r for r in held["items"]}
    items = [ragas_item(i) for i in load_items(HELDOUT_DIR) if i["id"] in report_rows]
    if args.only:
        items = [i for i in items if i["id"] in set(args.only)]
    by_id = {i["id"]: i for i in load_items(HELDOUT_DIR)}

    answers = load_site_answers(Path(args.answers))
    answer_config = args.answer_config or pick_answer_config(answers, report_rows)
    site = answers.get(answer_config) or {}
    print(f"{len(items)} items; answers from {answer_config}", flush=True)

    settings = load_settings()
    runtime = Runtime(settings)
    problems = check_settings(settings, held.get("run") or {}, index_info(settings.index_dir, len(runtime.index.chunks)))
    problems += check_code(held.get("run") or {})
    if problems and not args.ignore_settings:
        raise SystemExit("the passages can't be rebuilt as the run saw them: " + "; ".join(problems))
    answerer = runtime.answerer(llm=None)

    cache = rr.Cache(Path(args.cache))
    retrievals: Dict[str, Dict[str, Any]] = {}
    rebuilt = {"answers": 0, "found": 0, "cited": 0, "mismatched": 0, "retried": 0, "not_the_reports": 0}
    for item in items:
        record = site.get(item["id"])
        row = report_rows[item["id"]]
        if record and record.get("question_sha") not in (None, question_sha(by_id[item["id"]])):
            record = None  # the question was edited after the run: its answer is not this item's
        if record and not answer_matches(record, row):
            record = None  # a later answer for this item: judging it would score an answer the report doesn't hold
            rebuilt["not_the_reports"] += 1
        answer = (record or {}).get("answer")
        retried = bool(answer and answer.get("retried"))
        passages, shown = rebuild_passages(answerer, item, retried)
        retrievals[item["id"]] = page_retrieval(item, row.get("top") or [], passages, row.get("retrieval_ms"))
        if record is None:
            continue
        if answer:
            found, cited = excerpts_found(answer, shown)
            rebuilt.update(answers=rebuilt["answers"] + 1, found=rebuilt["found"] + found,
                           cited=rebuilt["cited"] + cited, mismatched=rebuilt["mismatched"] + (found < cited),
                           retried=rebuilt["retried"] + retried)
        # In memory only: the passages are rebuilt each run, and the cache file keeps just the verdicts.
        cache._index({"kind": "answer", "id": item["id"], "answer_config": answer_config, "at": record.get("at"),
                       "answer": answer, "error": record.get("error"), "passages": passages if answer else [],
                       "timing_ms": record.get("timing_ms"), "rebuilt": True})
    print(f"passages rebuilt for {rebuilt['answers']} answers: cited excerpts found {rebuilt['found']}/{rebuilt['cited']}; "
          f"{rebuilt['mismatched']} answers with a missing excerpt; {rebuilt['retried']} retried; "
          f"{rebuilt['not_the_reports']} cached answers left out as not the report's", flush=True)
    if rebuilt["mismatched"] > args.max_mismatch and not args.ignore_settings:
        raise SystemExit(f"{rebuilt['mismatched']} answers cite text the rebuilt passages don't hold "
                         f"(--max-mismatch {args.max_mismatch}): the judge would grade them on the wrong passages")

    if args.stage == "report" and not args.judge_models:
        # Score with the judges that gave the cached verdicts: the default (free) judge's labels find none
        # of an OpenAI judge's, and the report would come out without judge metrics.
        judge_configs = cached_judge_configs(cache, answer_config)
        if not judge_configs:
            raise SystemExit(f"no cached verdicts for {answer_config} in {args.cache}: run the judge stage first")
    else:
        ledger = SpendLedger(settings.openai_monthly_budget_usd, settings.openai_budget_margin_usd,
                             store_from_env(os.environ))
        judges = rr._judges(args, ledger)
        judge_configs = [label for _, label in judges]
    if args.stage in ("judge", "all"):
        judge, judge_config = judges[0]
        todo = [(i, cache.answer(i["id"], answer_config)) for i in items
                if rr.needs_judge(i, cache.answer(i["id"], answer_config))
                and rr.find_verdict(cache, i, answer_config, cache.answer(i["id"], answer_config), judge_configs) is None]
        print_estimate(todo, rr._priciest(judge))
        if args.dry_run:
            print("dry run: no judge calls made")
            return 0
        await rr.check_openai_budget(ledger, None, answer_config, judges, items, cache, args)
        stops = []
        for n, (client, config) in enumerate(judges):
            _, stopped = await rr.judge_stage(client, config, answer_config, items, cache, args, earlier=judge_configs[:n])
            stops += [stopped] if stopped else []
        stopped = "; ".join(stops) or None
    else:
        stopped = None
    scores = rr.report(items, retrievals, cache, answer_config, judge_configs, _Pipe(runtime), Path(args.scores),
                       Path(args.charts), stopped)
    scores["rebuilt"] = rebuilt
    scores["source_report"] = report_path.as_posix()
    Path(args.scores).write_text(json.dumps(scores, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown(scores, report_path, rebuilt, Path(args.markdown))
    print(f"markdown -> {args.markdown}")
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.heldout.ragas", description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True, help="the held-out run's report JSON (docs/heldout-set/NAME.json)")
    parser.add_argument("--stage", choices=("all", "judge", "report"), default="all",
                        help="report: rescore and redraw from the cached verdicts, no judge calls")
    parser.add_argument("--dry-run", action="store_true", help="rebuild the passages and print the cost, no judge calls")
    parser.add_argument("--only", nargs="*", help="item ids")
    parser.add_argument("--answers", default=str(CACHE_PATH), help="the held-out answer cache")
    parser.add_argument("--answer-config", help="the cached run to judge (default: the one whose answers are the report's)")
    parser.add_argument("--max-mismatch", type=int, default=3,
                        help="stop when more answers than this cite text the rebuilt passages don't hold")
    parser.add_argument("--ignore-settings", action="store_true", help="go on although the index or settings differ")
    parser.add_argument("--judge-base-url")
    parser.add_argument("--judge-models")
    parser.add_argument("--judge-reasoning", choices=("low", "medium", "high"))
    parser.add_argument("--fallback-judge-base-url")
    parser.add_argument("--fallback-judge-models")
    parser.add_argument("--fallback-judge-reasoning", choices=("low", "medium", "high"))
    parser.add_argument("--pause", type=float, default=0.5, help="seconds between judge calls")
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--start-anyway", action="store_true")
    parser.add_argument("--env-file")
    parser.add_argument("--cache", help="verdict cache (default evaluation/heldout/results/<report>-verdicts.jsonl)")
    parser.add_argument("--scores", help="default evaluation/heldout/results/<report>-scores.json")
    parser.add_argument("--charts", help="default evaluation/charts/heldout-<report>/")
    parser.add_argument("--markdown", help="default docs/heldout-set/ragas-<report>.md")
    args = parser.parse_args(list(argv) if argv is not None else None)
    stem = Path(args.report).stem
    args.cache = args.cache or str(RESULTS_DIR / f"{stem}-verdicts.jsonl")
    args.scores = args.scores or str(RESULTS_DIR / f"{stem}-scores.json")
    args.charts = args.charts or str(EVALUATION_DIR / "charts" / f"heldout-{stem}")
    args.markdown = args.markdown or str(ROOT / "docs" / "heldout-set" / f"ragas-{stem}.md")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
