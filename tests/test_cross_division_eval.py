"""Tests for the "All divisions" development-set runner (evaluation/cross_division/, DAR-666): which questions it asks
and how a two-division answer is scored, on the real pairs file and fake answers (no models, no network)."""

import json

from evaluation.cross_division.run import PAIRS_FILE, LOCKED_DIR, build_items, score, summarize
from evaluation.locked import load_items


def _gold():
    return {i["id"]: i for i in load_items(LOCKED_DIR)}


def test_the_pairs_join_two_divisions_tuning_questions_word_for_word():
    locked = load_items(LOCKED_DIR)
    gold = {i["id"]: i for i in locked}
    pairs = json.loads(PAIRS_FILE.read_text(encoding="utf-8"))["pairs"]
    items = build_items(locked, pairs)

    asked = [i for i in items if i["group"] == "pair"]
    assert len(asked) == len(pairs) >= 10
    for item in asked:
        first, second = (gold[p] for p in item["parts"])
        assert first["split"] == second["split"] == "tuning"  # never the locked or held-out questions
        assert first["division"] != second["division"]
        assert item["question"] == f"{first['question']} Also: {second['question']}" and item["target"] == "all"
    # Every other tuning question is asked twice: of its own division and of All divisions.
    tuning = [i for i in locked if i.get("split") == "tuning"]
    singles = [i for i in items if i["group"] != "pair"]
    assert len(singles) == 2 * len(tuning)
    assert {i["target"] for i in singles if i["id"].endswith("@all")} == {"all"}
    assert all(i["target"] == gold[i["parts"][0]]["division"] for i in singles if i["id"].endswith("@own"))


def _source(gold_item, page):
    from divrag.divisions import DIVISIONS

    doc = next(d for division in DIVISIONS for d in division.documents if d.file == gold_item["expected"]["source"])
    return {"url": f"{doc.url}#page={page}", "title": doc.title, "page": page, "division": gold_item["division"]}


def test_each_part_of_a_two_division_answer_is_scored_on_its_own_gold():
    gold = _gold()
    item = {"id": "x-01", "group": "pair", "target": "all", "parts": ["wztc-037", "utilities-026"]}
    first, second = gold["wztc-037"], gold["utilities-026"]
    payload = {"refused": False, "answer": "Seventy percent of the weight is in the base [1]. The pipe is filled to 80 percent [2].",
               "sources": [_source(first, first["expected"]["pdf_pages"][0]), _source(second, 1)]}
    passages = [{"source": first["expected"]["source"], "pages": first["expected"]["pdf_pages"]}]

    row = score(item, {"answer": payload, "passages": passages, "timing_ms": {"total": 9000}, "calls": 2,
                       "tokens": [9000, 120]}, gold)

    assert [(p["value_ok"], p["cited_ok"], p["in_passages"]) for p in row["parts"]] == [(True, True, True),
                                                                                          (False, False, False)]
    assert row["one_value_ok"] and not row["both_value_ok"]
    assert row["cited_divisions"] == ["utilities", "wztc"]
    summary = summarize([row], (1.0, 5.0))
    assert summary["pair"]["parts_value_ok"] == {"k": 1, "n": 2}
    # 9000 input and 120 output tokens at $1 and $5 per million.
    assert summary["time_cost_all"]["openai_usd_per_question"] == round((9000 + 600) / 1e6, 5)
