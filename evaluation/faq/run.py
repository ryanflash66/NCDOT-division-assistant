"""DAR-673: measure the checked-answer matcher on the FAQ test pairs and sweep its threshold.

    .venv/Scripts/python -m evaluation.faq.run                  # both sets, report to stdout
    .venv/Scripts/python -m evaluation.faq.run --write          # also rewrite evaluation/faq/RESULTS.md

Each set (pairs.json, pairs_holdout.json) has 30 stored questions; every
rewording and every similar-but-different question is looked up against all 30,
filtered to its own division, exactly as hosted/divrag/faq.py's best_match does
on the live site (numbers and units, contrast words, then cosine similarity of
the plain-text embeddings). A rewording counts only when it is served from its
own entry; a different question counts as a false match when anything is served.
Needs the embedding model (hosted/models, or it downloads into the cache).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hosted"))

from divrag.embedder import Embedder, model_cache_dir  # noqa: E402
from divrag.faq import DEFAULT_THRESHOLD, Entry, best_match, question_key  # noqa: E402

HERE = Path(__file__).resolve().parent
SETS = (("pairs.json", "written with the matcher (tuning)"),
        ("pairs_holdout.json", "written without seeing the matcher (held out)"))
SWEEP = (0.90, 0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98)


def _entry(item: Dict) -> Entry:
    return Entry(id=item["id"], division=item["division"], question=item["question"], answer="", sources=[],
                 checked_by="", checked_on="", asked={})


def evaluate(data: Dict, embedder: Embedder, threshold: float, rules: bool = True) -> Dict:
    entries = [_entry(f) for f in data["faq"]]
    questions = [e.question for e in entries] + [x["question"] for x in data["rewordings"] + data["different"]]
    vectors = dict(zip(questions, embedder.passages(questions)))

    def lookup(item: Dict) -> Tuple[Optional[str], float]:
        candidates = [(e, e.question, vectors[e.question]) for e in entries if e.division == item["division"]]
        if not rules:  # similarity alone, for the report: drop the word rules by giving every entry the question's key
            best = max(((e, float(v @ vectors[item["question"]])) for e, _, v in candidates), key=lambda t: t[1])
            return (best[0].id if best[1] >= threshold else None), best[1]
        match = best_match(item["question"], vectors[item["question"]], candidates, threshold)
        return (match.entry.id, match.similarity) if match else (None, 0.0)

    own = {x["faq"]: float(vectors[x["question"]] @ vectors[next(f for f in data["faq"] if f["id"] == x["faq"])["question"]])
           for x in data["rewordings"]}
    reworded = []
    for item in data["rewordings"]:
        served, _ = lookup(item)
        reworded.append({"faq": item["faq"], "question": item["question"], "served": served,
                         "right": served == item["faq"], "similarity": round(own[item["faq"]], 3),
                         "rules_pass": question_key(item["question"]) == question_key(
                             next(f for f in data["faq"] if f["id"] == item["faq"])["question"])})
    different = []
    for item in data["different"]:
        served, similarity = lookup(item)
        stored = next(f for f in data["faq"] if f["id"] == item["faq"])
        same_division = item["division"] == stored["division"]
        different.append({"faq": item["faq"], "kind": item["kind"], "question": item["question"], "served": served,
                          "similarity_to_stored": round(float(vectors[item["question"]] @ vectors[stored["question"]]), 3)
                          if same_division else None,
                          "rules_pass": same_division and question_key(item["question"]) == question_key(stored["question"])})
    return {"threshold": threshold, "rewordings_served": sum(r["right"] for r in reworded),
            "wrong_entry": sum(1 for r in reworded if r["served"] and not r["right"]),
            "different_served": sum(1 for d in different if d["served"]), "reworded": reworded, "different": different}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="rewrite evaluation/faq/RESULTS.md")
    args = parser.parse_args(argv)
    embedder = Embedder(cache_dir=model_cache_dir())
    lines = ["# DAR-673: checked-answer matcher on the FAQ test pairs", "",
             "Written by `python -m evaluation.faq.run --write`. Bar (ticket): rewordings served from their own entry "
             "at least 25/30, similar-but-different questions served 0/30.", ""]
    ok = True
    for name, what in SETS:
        data = json.loads((HERE / name).read_text(encoding="utf-8"))
        lines += [f"## {name}: {what}", "", "| threshold | rewordings served (own entry) | served the wrong entry | "
                  "different served | different served, similarity alone |", "|---|---|---|---|---|"]
        for threshold in SWEEP:
            with_rules = evaluate(data, embedder, threshold)
            alone = evaluate(data, embedder, threshold, rules=False)
            mark = " **(set)**" if abs(threshold - DEFAULT_THRESHOLD) < 1e-9 else ""
            lines.append(f"| {threshold:.2f}{mark} | {with_rules['rewordings_served']}/30 | {with_rules['wrong_entry']} | "
                         f"{with_rules['different_served']}/30 | {alone['different_served']}/30 |")
        chosen = evaluate(data, embedder, DEFAULT_THRESHOLD)
        ok = ok and chosen["rewordings_served"] >= 25 and chosen["different_served"] == 0 and chosen["wrong_entry"] == 0
        lines += ["", f"At {DEFAULT_THRESHOLD:.2f}, rewordings not served:", ""]
        for r in chosen["reworded"]:
            if not r["right"]:
                why = "number/unit or contrast word differs" if not r["rules_pass"] else f"similarity {r['similarity']}"
                lines.append(f"- {r['faq']} ({why}): {r['question']}")
        lines += ["", f"At {DEFAULT_THRESHOLD:.2f}, similar-but-different questions and what stopped them "
                  "(rule = numbers/units or contrast words; division = asked of another division):", "",
                  "| faq | kind | similarity to stored | stopped by | served |", "|---|---|---|---|---|"]
        for d in chosen["different"]:
            stop = ("division" if d["similarity_to_stored"] is None else "rule" if not d["rules_pass"]
                    else "threshold")
            sim = "" if d["similarity_to_stored"] is None else f"{d['similarity_to_stored']:.3f}"
            lines.append(f"| {d['faq']} | {d['kind']} | {sim} | {stop if not d['served'] else '-'} | "
                         f"{d['served'] or 'no'} |")
        lines.append("")
    report = "\n".join(lines) + "\n"
    print(report)
    if args.write:
        (HERE / "RESULTS.md").write_text(report, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
