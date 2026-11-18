"""Tests for the RAGAS judge on a held-out run's saved answers (evaluation/heldout/ragas.py, DAR-650):
the reference built from the gold value, matching a cached run to its report, the settings check that
keeps the rebuilt passages the site's, the cited-excerpt check and the (document, page) retrieval metrics."""

from types import SimpleNamespace

import pytest

from evaluation.heldout.ragas import (check_settings, excerpts_found, page_retrieval, pick_answer_config, ragas_item,
                                      reference_of)

TMP = "TMP Design Manual (Combined, No Links).pdf"


def _item(**changes):
    item = {"id": "wztc-h001", "division": "wztc", "asker": "utilities", "type": "table", "question": "How often?",
            "refuse": False, "split": "locked", "behaviour": "answer",
            "expected": {"source": TMP, "pdf_pages": [13], "value": "every mile", "unit": None}}
    item.update(changes)
    return item


def test_reference_is_the_gold_value_with_its_unit():
    assert reference_of(_item()) == "every mile"
    assert reference_of(_item(expected={"source": TMP, "pdf_pages": [13], "value": "200", "unit": "ft"})) == "200 ft"
    assert reference_of(_item(expected={"source": TMP, "pdf_pages": [13], "value": "200 ft", "unit": "ft"})) == "200 ft"


def test_reference_lists_every_all_of_part_by_its_first_wording():
    expected = {"source": TMP, "pdf_pages": [13], "value": None, "all_of": [["half mile", "0.5 mile"], "every mile"]}
    assert reference_of(_item(behaviour="clarify", expected=expected)) == "half mile; every mile"


def test_must_refuse_items_have_no_reference_and_are_not_answerable():
    item = ragas_item(_item(refuse=True, behaviour="refuse", expected=None, type="unanswerable"))
    assert item["reference"] is None and item["answerable"] is False and item["gold_pages"] == []


def test_ragas_item_carries_target_split_and_gold_page():
    item = ragas_item(_item())
    assert (item["target"], item["holdout"], item["gold_source"], item["gold_pages"]) == ("wztc", True, TMP, [13])


def _record(text):
    return {"answer": {"answer": text}}


def test_the_cached_run_whose_answers_are_the_reports_is_picked():
    rows = {"a": {"answer": "x"}, "b": {"answer": "y"}}
    answers = {"old": {"a": _record("x"), "b": _record("other")}, "new": {"a": _record("x"), "b": _record("y")}}
    assert pick_answer_config(answers, rows) == "new"


def test_no_matching_run_stops():
    with pytest.raises(SystemExit):
        pick_answer_config({"old": {"a": _record("z")}}, {"a": {"answer": "x"}})


def _settings(**changes):
    values = {"top_k": 5, "rerank": True, "keyword_search": True, "rerank_candidates": 40}
    values.update(changes)
    return SimpleNamespace(**values)


def test_settings_and_index_must_be_the_runs():
    run = {"index": {"sha256_12": "abc"}, "settings": {"top_k": 5, "rerank": True, "keyword_search": True,
                                                       "rerank_candidates": 40}}
    assert check_settings(_settings(), run, {"sha256_12": "abc"}) == []
    problems = check_settings(_settings(rerank_candidates=20), run, {"sha256_12": "def"})
    assert len(problems) == 2 and "rerank_candidates" in problems[1]


def test_cited_excerpts_are_found_among_the_rebuilt_passages_excerpts():
    shown = ["Signs W8-11 are repeated every mile …", "Another passage."]
    answer = {"sources": [{"excerpt": "Signs W8-11 are repeated every mile …"},
                          {"excerpt": "A sentence no passage holds …"}, {"excerpt": None}]}
    assert excerpts_found(answer, shown) == (1, 2)


def test_page_metrics_count_a_page_only_in_its_own_document():
    item = ragas_item(_item())
    passages = [{"source": "Other.pdf", "pages": [13]}, {"source": TMP, "pages": [14]}]
    miss = page_retrieval(item, ["Other.pdf p.13", f"{TMP} p.14"], passages, 400)
    assert (miss["hit"], miss["recall"]) == (0.0, 0.0)
    hit = page_retrieval(item, ["Other.pdf p.13", f"{TMP} p.13"], [{"source": TMP, "pages": [13]}], 400)
    assert (hit["hit"], hit["rr"], hit["recall"], hit["retrieval_ms"]) == (1.0, 0.5, 1.0, 400)


def test_an_openai_judge_is_asked_as_the_site_asks_openai():
    from evaluation.judge import ChatClient

    client = ChatClient("https://api.openai.com/v1", "k", ["gpt-6.1-terra"], max_tokens=8000, json_mode=True)
    body = client._body([{"role": "user", "content": "q"}], "gpt-6.1-terra", ["gpt-6.1-terra"])
    assert "max_tokens" not in body and body["max_completion_tokens"] == 8000
    assert body["reasoning_effort"] == "none" and body["temperature"] == 0.0
    thinking = ChatClient("https://api.openai.com/v1", "k", ["gpt-6.1-terra"], reasoning="low")
    assert "temperature" not in thinking._body([], "gpt-6.1-terra", ["gpt-6.1-terra"])
    local = ChatClient("http://localhost:11434/v1", "k", ["qwen"], max_tokens=10)._body([], "qwen", ["qwen"])
    assert local["max_tokens"] == 10 and "reasoning_effort" not in local
