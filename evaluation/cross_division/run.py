"""Score "All divisions" (DAR-666) on development questions, and measure its time and cost per question.

    py -m evaluation.cross_division.run --label NAME [--env-file PATH] [--only ID ...] [--max-requests N]

Three groups of questions, all from the locked set's tuning split (a development set: its items
have been read while fixing the pipeline) and never from the locked or held-out splits:

    pair     the cross-division questions in pairs.json: two tuning questions from two divisions,
             asked together of "All divisions"; each part is scored on its own gold
    single   each answerable tuning question, asked of its own division and again of
             "All divisions" (paired): what asking everything costs a one-division question
    refuse   each must-refuse tuning question, the same two ways; asked of all divisions,
             an answer may be right if another division's documents cover it, so those are
             listed for reading, not counted wrong

The answers come from the hosted Answerer in-process, as /api/ask gives them (evaluation.locked
Runtime, run_ragas.answer_one), with the free OpenRouter models the local .env selects. Every
model call is counted, and its tokens are estimated from the prompt and reply text as the spend
ledger does without a usage report (spend.estimated_usage); the cost column prices them at the
production OpenAI model's rate (OPENAI_MODEL, config.DEFAULT_OPENAI_MODEL). Local time is not
Vercel's: the reranker runs about 12 times slower there (retrieval.DEFAULT_CANDIDATES).

Answers are cached in evaluation/cross_division/results/cache.jsonl (gitignored), keyed by item and
the code's configuration, so a stopped run resumes. The report goes to docs/cross-division/<label>.{json,md}.
"""

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from evaluation import ROOT
from evaluation.locked import load_items
from evaluation.locked.normalize import value_matches
from evaluation.locked.score import cited_pages, score_item, source_file
from evaluation.run_ragas import OPENROUTER_URL, Cache, Stop, _with_busy_waits, answer_one, config_label

HERE = Path(__file__).resolve().parent
PAIRS_FILE = HERE / "pairs.json"
CACHE_PATH = HERE / "results" / "cache.jsonl"
DOCS_DIR = ROOT / "docs" / "cross-division"
LOCKED_DIR = ROOT / "evaluation" / "locked"


def build_items(locked: Sequence[Dict[str, Any]], pairs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every question to ask: id, group, target ("all" or a division), asker, question, and the gold items it uses."""
    tuning = {i["id"]: i for i in locked if i.get("split") == "tuning"}
    items: List[Dict[str, Any]] = []
    for pair in pairs:
        parts = [tuning[p] for p in pair["parts"]]
        if len({p["division"] for p in parts}) < 2:
            raise ValueError(f"{pair['id']}: its parts must come from two divisions")
        items.append({"id": pair["id"], "group": "pair", "target": "all", "asker": parts[0].get("asker") or parts[0]["division"],
                      "question": " Also: ".join(p["question"] for p in parts), "parts": [p["id"] for p in parts]})
    for item in tuning.values():
        group = "refuse" if item.get("refuse") else "single"
        for target in (item["division"], "all"):
            items.append({"id": f"{item['id']}@{'all' if target == 'all' else 'own'}", "group": group, "target": target,
                          "asker": item.get("asker") or item["division"], "question": item["question"],
                          "parts": [item["id"]]})
    return items


def _cited_part(payload: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    """Some cited source is on the part's gold document and one of its gold pages."""
    for source in payload.get("sources") or []:
        pages = range(source.get("page") or 0, (source.get("page_end") or source.get("page") or 0) + 1)
        if source_file(source) == expected["source"] and set(pages) & set(expected["pdf_pages"]):
            return True
    return False


def _in_passages(passages: Sequence[Dict[str, Any]], expected: Dict[str, Any]) -> bool:
    """The part's gold page was among the passages the model read."""
    return any(p.get("source") == expected["source"] and set(p.get("pages") or [p.get("page")]) & set(expected["pdf_pages"])
               for p in passages)


def score(item: Dict[str, Any], record: Dict[str, Any], gold: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """One row: what was asked, its outcome, per-part scores, time and cost."""
    payload = record.get("answer")
    passages = record.get("passages") or []
    row: Dict[str, Any] = {"id": item["id"], "group": item["group"], "target": item["target"], "error": record.get("error"),
                           "ms": record.get("timing_ms"), "calls": record.get("calls"), "tokens": record.get("tokens"),
                           "passages": len(passages), "passage_divisions": sorted({p.get("division") for p in passages if p.get("division")})}
    if payload is None:
        return row
    row.update(refused=bool(payload.get("refused")), uncited=bool(payload.get("uncited")), answer=payload.get("answer"),
               cited_divisions=sorted({s.get("division") for s in payload.get("sources") or []}))
    if item["group"] == "pair":
        text = payload.get("answer") or ""
        parts = []
        for part_id in item["parts"]:
            expected = gold[part_id]["expected"]
            value = not row["refused"] and value_matches(expected.get("value"), expected.get("accept"), text)
            cited = not row["refused"] and _cited_part(payload, expected)
            parts.append({"id": part_id, "division": gold[part_id]["division"], "value_ok": value,
                          "cited_ok": cited, "in_passages": _in_passages(passages, expected)})
        row.update(parts=parts, both_value_ok=all(p["value_ok"] for p in parts),
                   both_strict_ok=all(p["value_ok"] and p["cited_ok"] for p in parts),
                   one_value_ok=sum(p["value_ok"] for p in parts) == 1)
        return row
    base = gold[item["parts"][0]]
    scored = score_item(dict(base, division=base["division"]), None, payload, error=record.get("error"),
                        cited=cited_pages(payload))
    row.update({k: scored[k] for k in ("value_ok", "strict_ok", "critical", "over_refusal", "false_answer")})
    if base.get("expected"):
        row["in_passages"] = _in_passages(passages, base["expected"])
    return row


class _Counting:
    """The model client with every call's tokens counted (estimated from the text, as spend.py does without usage)."""

    def __init__(self, llm):
        from divrag.spend import estimated_usage

        self._estimate = estimated_usage
        self.llm = llm
        self.calls = 0
        self.tokens = [0, 0]
        complete = llm.complete

        async def counted(messages, models=None):
            result = await complete(messages, models)
            tokens = self._estimate(messages, result.text)
            self.calls += 1
            self.tokens[0] += tokens[0]
            self.tokens[1] += tokens[1]
            return result

        llm.complete = counted

    def reset(self) -> None:
        self.calls, self.tokens = 0, [0, 0]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git(*args: str) -> Optional[str]:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(statistics.mean(values), 1) if values else None


def _median(values: Sequence[float]) -> Optional[float]:
    return round(statistics.median(values), 1) if values else None


def summarize(rows: Sequence[Dict[str, Any]], prices) -> Dict[str, Any]:
    """Counts per group and target, and time and cost per question for each target kind."""
    def count(selected, key):
        values = [r.get(key) for r in selected if r.get(key) is not None]
        return {"k": sum(bool(v) for v in values), "n": len(values)}

    out: Dict[str, Any] = {}
    pairs = [r for r in rows if r["group"] == "pair" and "parts" in r]
    out["pair"] = {"n": len(pairs), "both_value_ok": count(pairs, "both_value_ok"),
                   "both_strict_ok": count(pairs, "both_strict_ok"), "one_value_ok": count(pairs, "one_value_ok"),
                   "refused": count(pairs, "refused"),
                   "parts_value_ok": {"k": sum(p["value_ok"] for r in pairs for p in r["parts"]), "n": 2 * len(pairs)},
                   "parts_in_passages": {"k": sum(p["in_passages"] for r in pairs for p in r["parts"]), "n": 2 * len(pairs)},
                   "cited_two_divisions": {"k": sum(len(r.get("cited_divisions") or []) >= 2 for r in pairs), "n": len(pairs)}}
    for group in ("single", "refuse"):
        for kind in ("own", "all"):
            selected = [r for r in rows if r["group"] == group and (r["target"] == "all") == (kind == "all")]
            block = {"n": len(selected), "refused": count(selected, "refused")}
            if group == "single":
                block.update(value_ok=count(selected, "value_ok"), strict_ok=count(selected, "strict_ok"),
                             critical=count(selected, "critical"), over_refusal=count(selected, "over_refusal"),
                             in_passages=count(selected, "in_passages"))
            else:
                block.update(false_answer=count(selected, "false_answer"))
            out[f"{group}_{kind}"] = block
    for kind in ("own", "all"):
        selected = [r for r in rows if r.get("ms") and (r["target"] == "all") == (kind == "all")]
        totals = [r["ms"]["total"] / 1000 for r in selected]
        retrieval = [r["ms"].get("retrieval", 0) / 1000 for r in selected]
        rerank = [r["ms"].get("rerank", 0) / 1000 for r in selected]
        calls = [r["calls"] for r in selected if r.get("calls") is not None]
        tokens_in = [r["tokens"][0] for r in selected if r.get("tokens")]
        tokens_out = [r["tokens"][1] for r in selected if r.get("tokens")]
        cost = None
        if prices and tokens_in:
            cost = round((statistics.mean(tokens_in) * prices[0] + statistics.mean(tokens_out) * prices[1]) / 1e6, 5)
        out[f"time_cost_{kind}"] = {"n": len(selected), "total_s_mean": _mean(totals), "total_s_median": _median(totals),
                                    "retrieval_s_mean": _mean(retrieval), "rerank_s_mean": _mean(rerank),
                                    "passages_mean": _mean([r["passages"] for r in selected]),
                                    "calls_mean": _mean(calls), "input_tokens_mean": _mean(tokens_in),
                                    "output_tokens_mean": _mean(tokens_out), "openai_usd_per_question": cost}
    return out


def render(report: Dict[str, Any]) -> str:
    s, meta = report["summary"], report["meta"]

    def kn(stat):
        return f"{stat['k']}/{stat['n']}" if stat and stat.get("n") else "-"

    lines = [f"# All divisions (DAR-666): {meta['label']}", "",
             f"Commit `{meta['commit']}`, {meta['at']}, models {', '.join(meta['models'])}; "
             f"ALL_DIVISIONS_TOP_K {meta['all_divisions_top_k']}, ALL_DIVISIONS_CANDIDATES {meta['all_divisions_candidates']}, "
             f"TOP_K {meta['top_k']}. Development questions only (the locked set's tuning split); see "
             "`evaluation/cross_division/run.py`.", "",
             "## Cross-division questions (two divisions in one question, asked of All divisions)", "",
             "| | count |", "|---|---|"]
    p = s["pair"]
    lines += [f"| both parts' values right | {kn(p['both_value_ok'])} |",
              f"| both right, each citing its gold page | {kn(p['both_strict_ok'])} |",
              f"| only one part right | {kn(p['one_value_ok'])} |",
              f"| refused | {kn(p['refused'])} |",
              f"| parts with the right value | {kn(p['parts_value_ok'])} |",
              f"| parts whose gold page was in the first passages (before any second look) | {kn(p['parts_in_passages'])} |",
              f"| answers citing two or more divisions | {kn(p['cited_two_divisions'])} |", "",
              "## One-division questions asked of their division and of All divisions", "",
              "| | own division | All divisions |", "|---|---|---|"]
    for key, label in (("value_ok", "value right"), ("strict_ok", "value right, citing the gold page"),
                       ("critical", "confident wrong"), ("over_refusal", "answerable but refused"),
                       ("in_passages", "gold page in the first passages")):
        lines.append(f"| {label} | {kn(s['single_own'].get(key))} | {kn(s['single_all'].get(key))} |")
    lines += [f"| must-refuse questions answered | {kn(s['refuse_own'].get('false_answer'))} | "
              f"{kn(s['refuse_all'].get('false_answer'))} (read below: another division may cover them) |", "",
              "## Time and cost per question (local CPU; free models answered, cost priced at "
              f"{meta['cost_model']})", "",
              "| | own division | All divisions |", "|---|---|---|"]
    for key, label in (("n", "questions"), ("total_s_mean", "total s, mean"), ("total_s_median", "total s, median"),
                       ("retrieval_s_mean", "retrieval s, mean"), ("rerank_s_mean", "rerank s, mean"),
                       ("passages_mean", "passages the model read, mean"), ("calls_mean", "model calls, mean"),
                       ("input_tokens_mean", "input tokens, mean (estimated)"),
                       ("output_tokens_mean", "output tokens, mean (estimated)"),
                       ("openai_usd_per_question", "OpenAI $ per question (estimated)")):
        lines.append(f"| {label} | {s['time_cost_own'].get(key)} | {s['time_cost_all'].get(key)} |")
    lines += ["", "## Every cross-division question", "", "| id | parts | value | cited | in passages | divisions cited |",
              "|---|---|---|---|---|---|"]
    for r in report["rows"]:
        if r["group"] != "pair" or "parts" not in r:
            continue
        mark = lambda key: " ".join("yes" if part[key] else "no" for part in r["parts"])  # noqa: E731
        lines.append(f"| {r['id']} | {' + '.join(part['id'] for part in r['parts'])} | {mark('value_ok')} | "
                     f"{mark('cited_ok')} | {mark('in_passages')} | {', '.join(r.get('cited_divisions') or []) or '-'} |")
    refuse_all = [r for r in report["rows"] if r["group"] == "refuse" and r["target"] == "all" and r.get("refused") is False]
    if refuse_all:
        lines += ["", "## Must-refuse questions answered when asked of All divisions", ""]
        for r in refuse_all:
            lines.append(f"- {r['id']} (cited {', '.join(r.get('cited_divisions') or []) or 'nothing'}): "
                         f"{(r.get('answer') or '').replace(chr(10), ' ')[:300]}")
    return "\n".join(lines) + "\n"


async def run(args) -> int:
    from divrag.config import DEFAULT_OPENAI_MODEL, load_settings
    from divrag.llm import TOO_LONG, TOO_SLOW, LLMError, client_from_settings
    from divrag.spend import price_for
    from evaluation.locked.run import Runtime, _load_env

    _load_env(args.env_file)
    settings = load_settings()
    locked = load_items(LOCKED_DIR)
    gold = {i["id"]: i for i in locked}
    items = build_items(locked, json.loads(PAIRS_FILE.read_text(encoding="utf-8"))["pairs"])
    if args.only:
        items = [i for i in items if i["id"] in args.only or i["id"].split("@")[0] in args.only]
    runtime = Runtime(settings)
    llm = client_from_settings(settings)
    counting = _Counting(llm)
    answer_config = (f"{config_label(OPENROUTER_URL, settings.answer_models)}"
                     f"#k{settings.top_k}#all{settings.all_divisions_top_k}-{settings.all_divisions_candidates}")
    cache = Cache(Path(args.cache))
    todo = [i for i in items if cache.answer(i["id"], answer_config) is None]
    print(f"{len(items)} questions: {len(items) - len(todo)} cached, {len(todo)} to ask ({answer_config})", flush=True)
    for n, item in enumerate(todo, 1):
        if args.max_requests is not None and n > args.max_requests:
            print(f"stopped after --max-requests {args.max_requests}")
            break
        counting.reset()
        record = {"kind": "answer", "id": item["id"], "answer_config": answer_config, "at": _now()}
        try:
            record.update(await _with_busy_waits(lambda: answer_one(runtime, llm, item, settings.request_budget_seconds),
                                                 item["id"]))
        except Stop as stop:
            print(stop)
            break
        except LLMError as exc:
            if exc.user_message not in (TOO_SLOW, TOO_LONG):
                print(f"  [{n}/{len(todo)}] {item['id']}: {exc.user_message}; asked again next run", flush=True)
                await asyncio.sleep(args.pause)
                continue
            record.update({"answer": None, "error": exc.user_message, "passages": [], "timing_ms": None})
        for passage in record.get("passages") or []:
            passage.pop("text", None)  # the cache keeps what scoring needs, not the documents' text
        record.update(calls=counting.calls, tokens=list(counting.tokens))
        cache.add(record)
        answer = record.get("answer") or {}
        state = record.get("error") or ("refused" if answer.get("refused") else "answered")
        print(f"  [{n}/{len(todo)}] {item['id']}: {state} in {(record.get('timing_ms') or {}).get('total', 0) / 1000:.1f}s",
              flush=True)
        await asyncio.sleep(args.pause)

    divisions_by_source = {c.get("source"): c.get("division") for c in runtime.index.chunks}
    rows = []
    for item in items:
        record = cache.answer(item["id"], answer_config)
        if record is None:
            continue
        for passage in record.get("passages") or []:
            passage["division"] = divisions_by_source.get(passage.get("source"))
        rows.append(score(item, record, gold))
    prices = price_for(settings.openai_model or DEFAULT_OPENAI_MODEL)
    report = {"meta": {"label": args.label, "commit": _git("rev-parse", "--short", "HEAD"), "at": _now(),
                       "models": list(settings.answer_models), "answer_config": answer_config,
                       "top_k": settings.top_k, "all_divisions_top_k": settings.all_divisions_top_k,
                       "all_divisions_candidates": settings.all_divisions_candidates,
                       "cost_model": f"{settings.openai_model or DEFAULT_OPENAI_MODEL} {prices}",
                       "asked": len(rows), "of": len(items)},
              "summary": summarize(rows, prices), "rows": rows}
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / f"{args.label}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (DOCS_DIR / f"{args.label}.md").write_text(render(report), encoding="utf-8")
    print(f"wrote docs/cross-division/{args.label}.md ({len(rows)}/{len(items)} questions)")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--pause", type=float, default=2.0)
    parser.add_argument("--cache", default=str(CACHE_PATH))
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
