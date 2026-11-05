"""Tests for the locked test set tooling (evaluation/locked/): normalization, scoring, the split rule,
freeze/check, the validator and the runner's report, all on fakes (no models, no network)."""

import json
from pathlib import Path

import pytest

from evaluation.locked import canonical_json, load_items, locked_digest, split_of
from evaluation.locked.normalize import normalize, numbers_with_units, value_matches
from evaluation.locked.run import (Runtime, build_report, cached_answer, check_command, freeze_command, main,
                                   question_sha, render_markdown, score_rows, write_outputs)
from evaluation.locked.score import aggregate, printed_range, score_item, wilson, zero_failure_upper
from evaluation.locked.validate import validate_items
from evaluation.run_ragas import Cache

FIXTURES = Path(__file__).parent / "fixtures" / "locked_questions"
TMP = "TMP Design Manual (Combined, No Links).pdf"
TMP_URL = "https://connect.ncdot.gov/projects/WZTC/Documents/TMP%20Design%20Manual%20%28Combined%2C%20No%20Links%29.pdf"
TMP_TITLE = "Work Zone Traffic Control Design Manual (TMP Design Manual)"


# --- normalization ----------------------------------------------------------------

@pytest.mark.parametrize("raw, clean", [
    ("1,640 ft", "1640 ft"),
    ("1/2 inch", "0.5 in"),
    ("1-1/2 inches", "1.5 in"),
    ("1 1/2\"", "1.5 in"),
    ("½ inch", "0.5 in"),
    ("12'", "12 ft"),
    ("12-foot", "12 ft"),
    ("12 feet", "12 ft"),
    ("12 ft.", "12 ft"),
    ("12 in.", "12 in"),
    ("12 into the lane", "12 into the lane"),
    ("45 MPH", "45 mph"),
    ("45 mi/h", "45 mph"),
    ("60 miles per hour", "60 mph"),
    ("95 percent", "95 %"),
    ("95%", "95 %"),
    ("11.5°", "11.5 deg"),
    ("11.5 degrees", "11.5 deg"),
    ("12.0 ft", "12 ft"),
    ("12.50", "12.5"),
    ("27.42 ft", "27.42 ft"),
    ("Section 3.6.4.1", "section 3.6.4.1"),
    ("the width in feet", "the width in feet"),
    ("reduce to 11 in the work zone", "reduce to 11 in the work zone"),
    ("12 in. wide", "12 in wide"),
    ("a 12 in wide strip", "a 12 in wide strip"),
])
def test_normalize_rules(raw, clean):
    assert normalize(raw) == clean


def test_numbers_with_units_reads_values_and_units():
    assert numbers_with_units("Deflection is 27.42 feet at 11.5°; use a 1/2\" gap, 1,640 ft radius") == [
        (27.42, "ft", "27.42 ft"), (11.5, "deg", "11.5 deg"), (0.5, "in", "0.5 in"), (1640.0, "ft", "1640 ft")]
    assert numbers_with_units("no numbers here") == []


def test_value_matches_numbers_within_tolerance_and_units():
    assert value_matches("27.42", ["27.42 ft"], "The maximum deflection is 27.42 feet [1].")
    assert value_matches("27.42", [], "about 27.420 ft")
    assert not value_matches("27.42", [], "The maximum deflection is 27.4 feet [1].")
    assert value_matches("0.5 in", [], 'Leave a 1/2" gap')
    assert not value_matches("27.42 ft", [], "The maximum deflection is 27.42 inches [1].")  # unit must agree
    assert value_matches("2 in", ["two inches"], "Two inches at most.")  # an accepted phrase
    assert not value_matches("2 in", ["two inches"], "Three inches at most.")


def test_value_matches_phrases_case_and_whitespace_insensitively():
    assert value_matches("16:1 anchored", [], "Slope   16:1  Anchored, 12:1 unanchored")
    assert not value_matches("16:1 anchored", [], "Slope 16:1 when anchored")
    assert not value_matches(None, [], "anything")
    assert not value_matches("", [""], "anything")


# --- intervals -----------------------------------------------------------------------

def test_wilson_matches_known_values():
    low, high = wilson(14, 15)
    assert low == pytest.approx(0.702, abs=0.002) and high == pytest.approx(0.988, abs=0.002)
    assert wilson(0, 50)[0] == 0.0 and wilson(0, 50)[1] == pytest.approx(0.0713, abs=0.001)
    assert wilson(50, 50)[1] == 1.0
    assert wilson(0, 0) == (0.0, 1.0)
    # The research note's "0 of 50 failures" bound is the one-sided Clopper-Pearson one: 5.8%.
    assert zero_failure_upper(50) == pytest.approx(0.058, abs=0.001)
    assert zero_failure_upper(0) is None


# --- the split rule -----------------------------------------------------------------------

def test_split_is_by_gold_page_and_by_question_when_unanswerable():
    page37 = {"question": "a", "expected": {"source": TMP, "pdf_pages": [37]}, "refuse": False}
    same_page = {"question": "b (worded differently)", "expected": {"source": TMP, "pdf_pages": [37, 38]}, "refuse": False}
    assert split_of(page37) == split_of(same_page) == "locked"  # sha1("...|37") ends in 4
    assert split_of({"question": "a", "expected": {"source": TMP, "pdf_pages": [23]}, "refuse": False}) == "tuning"
    assert split_of({"question": "What is the speed of light in a vacuum?", "expected": None, "refuse": True}) == "tuning"
    assert split_of({"question": "How many moons does Mars have?", "expected": None, "refuse": True}) == "locked"


# --- scoring ----------------------------------------------------------------------------

ITEM = {"id": "wztc-001", "division": "wztc", "asker": "utilities", "type": "table", "edge_cases": ["landscape"],
        "split": "locked", "refuse": False, "question": "What is the maximum deflection at 14 ft and 40 mph?",
        "expected": {"source": TMP, "pdf_pages": [37], "printed_pages": ["13"], "value": "27.42", "accept": ["27.42 ft"]}}
NEGATIVE = {"id": "wztc-009", "division": "wztc", "asker": "wztc", "type": "unanswerable", "split": "locked",
            "refuse": True, "expected": None}
RANKED = [{"source": "Chapter_5.pdf", "page": 4}, {"source": TMP, "page": 38}, {"source": TMP, "page": 37}]


def _source(page, page_end=None, printed=..., printed_end=None, url=TMP_URL, title=TMP_TITLE):
    source = {"n": 1, "division": "wztc", "title": title, "page": page, "page_end": page_end, "section": None,
              "url": f"{url}#page={page}", "excerpt": "..."}
    if printed is not ...:
        source.update(printed_page=printed, printed_page_end=printed_end)
    return source


def _payload(text="The maximum deflection is 27.42 ft [1].", sources=(), refused=False, uncited=False, **extra):
    return {"answer": text, "refused": refused, "uncited": uncited, "sources": list(sources), "model": "m:free",
            "first_model": "m:free", "retried": False, "suggest": [], **extra}


def test_right_page_right_value_is_strictly_ok():
    row = score_item(ITEM, RANKED, _payload(sources=[_source(37)]), seconds=3.2)
    assert (row["right_document"], row["page_rank"], row["hit1"], row["hit5"]) == (True, 3, False, True)
    assert row["cited_pages_pdf"] == [{"file": TMP, "page": 37, "page_end": None}]
    assert row["cited_page_ok_pdf"] and row["value_ok"] and row["strict_ok"]
    assert row["critical"] is False and row["over_refusal"] is False and row["seconds"] == 3.2
    assert row["cited_page_ok_printed"] is None and row["unverified"] is None  # the API sent no printed pages


def test_wrong_page_with_the_right_value_is_not_strict_and_not_critical():
    row = score_item(ITEM, RANKED, _payload(sources=[_source(38)]))
    assert row["value_ok"] and not row["cited_page_ok_pdf"] and not row["strict_ok"] and row["critical"] is False


def test_a_cited_range_counts_when_it_overlaps_the_gold_page_and_other_documents_never_do():
    assert score_item(ITEM, RANKED, _payload(sources=[_source(36, page_end=37)]))["cited_page_ok_pdf"]
    other = _source(37, url="https://connect.ncdot.gov/projects/WZTC/Documents/Chapter_5.pdf", title="x")
    assert not score_item(ITEM, RANKED, _payload(sources=[_source(37), other]))["cited_page_ok_pdf"]


def test_wrong_value_with_a_citation_is_critical_but_uncited_is_not():
    wrong = score_item(ITEM, RANKED, _payload("It is 25.37 ft [1].", sources=[_source(37)]))
    assert wrong["value_ok"] is False and wrong["strict_ok"] is False and wrong["critical"] is True
    uncited = score_item(ITEM, RANKED, _payload("It is 25.37 ft.", uncited=True))
    assert uncited["uncited"] and uncited["critical"] is False and uncited["cited_page_ok_pdf"] is False


def test_refusing_an_answerable_question_is_over_refusal_and_refusing_an_unanswerable_one_is_right():
    refused = score_item(ITEM, RANKED, _payload("I couldn't find it.", refused=True))
    assert refused["over_refusal"] and refused["value_ok"] is False and refused["cited_page_ok_pdf"] is None
    good = score_item(NEGATIVE, RANKED, _payload("I couldn't find it.", refused=True))
    assert good["false_answer"] is False and good["critical"] is False and good["value_ok"] is None
    assert good["right_document"] is None and good["page_rank"] is None
    false = score_item(NEGATIVE, RANKED, _payload("The speed is 3e8 [1].", sources=[_source(5)]))
    assert false["false_answer"] is True and false["critical"] is True


def test_unverified_numbers_pass_through_from_the_payload():
    row = score_item(ITEM, RANKED, _payload(sources=[_source(37)], unverified=["27.42"]))
    assert row["unverified"] == ["27.42"]


def test_a_flagged_answer_with_the_right_value_is_a_false_flag():
    # DAR-659 reports the unverified rate and the guardrail's false alarms on the locked set.
    right = score_item(ITEM, RANKED, _payload(sources=[_source(37)], unverified=["27.42"]))
    clean = score_item(ITEM, RANKED, _payload(sources=[_source(37)], unverified=[]))
    wrong = score_item(ITEM, RANKED, _payload("It is 25.37 ft [1].", sources=[_source(37)], unverified=["25.37"]))
    old = score_item(ITEM, RANKED, _payload(sources=[_source(37)]))  # an API without the guardrail
    refused = score_item(ITEM, RANKED, _payload("I couldn't find it.", refused=True, unverified=[]))

    assert (right["flagged"], right["false_flag"]) == (True, True)
    assert (clean["flagged"], clean["false_flag"]) == (False, False)
    assert (wrong["flagged"], wrong["false_flag"]) == (True, None)
    assert (old["flagged"], old["false_flag"]) == (None, None)
    assert (refused["flagged"], refused["false_flag"]) == (None, None)


def test_printed_page_is_scored_only_when_the_api_sends_it():
    assert score_item(ITEM, RANKED, _payload(sources=[_source(37, printed="13")]))["cited_page_ok_printed"] is True
    assert score_item(ITEM, RANKED, _payload(sources=[_source(37, printed="14")]))["cited_page_ok_printed"] is False
    assert score_item(ITEM, RANKED, _payload(sources=[_source(37, printed=None)]))["cited_page_ok_printed"] is False
    mixed = _payload(sources=[_source(37, printed="13"), _source(37)])
    assert score_item(ITEM, RANKED, mixed)["cited_page_ok_printed"] is None
    no_gold = dict(ITEM, expected=dict(ITEM["expected"], printed_pages=[""]))
    assert score_item(no_gold, RANKED, _payload(sources=[_source(37, printed="13")]))["cited_page_ok_printed"] is None


def test_not_run_stages_leave_their_fields_undefined():
    row = score_item(ITEM, None, None)
    assert row["top"] is None and row["hit5"] is None and row["refused"] is None and row["answered"] is False
    failed = score_item(ITEM, RANKED, None, error="too slow")
    assert failed["error"] == "too slow" and failed["hit5"] is True and failed["value_ok"] is None


def test_aggregate_counts_strata_clusters_and_the_abstention_table():
    items = [ITEM, dict(ITEM, id="wztc-002", asker="wztc", type="text"), NEGATIVE]
    rows = [score_item(ITEM, RANKED, _payload(sources=[_source(37)])),
            score_item(items[1], RANKED, _payload("Refused", refused=True)),
            score_item(NEGATIVE, RANKED, _payload("Refused", refused=True))]
    agg = aggregate(rows, items)
    assert agg["all"]["n"] == 3 and agg["all"]["clusters"] == 1 and agg["all"]["unanswerable"] == 1
    assert agg["all"]["metrics"]["strict_ok"] == {"k": 1, "n": 2, "rate": 0.5, "ci": list(wilson(1, 2))}
    assert agg["all"]["metrics"]["critical"]["k"] == 0 and agg["all"]["metrics"]["critical"]["upper_if_zero"] is not None
    assert agg["abstention"]["answerable"] == {"answered": 1, "refused": 1, "n": 2}
    assert agg["abstention"]["unanswerable"] == {"answered": 0, "refused": 1, "n": 1}
    assert agg["abstention"]["over_refusal"]["k"] == 1 and agg["abstention"]["false_answer"]["k"] == 0
    assert set(agg["type"]) == {"table", "text", "unanswerable"} and set(agg["edge_case"]) == {"landscape"}
    assert set(agg["asker"]) == {"cross-division", "same division"}
    assert agg["asker"]["cross-division"]["n"] == 1


# --- question files, freeze/check and the validator ----------------------------------------

def test_fixture_loads_validates_and_filters_by_split():
    items = load_items(FIXTURES)
    assert [i["id"] for i in items] == [f"wztc-fx-00{n}" for n in range(1, 6)]
    assert validate_items(items) == []
    assert [i["id"] for i in load_items(FIXTURES, split="tuning")] == ["wztc-fx-003", "wztc-fx-004"]
    assert [i["id"] for i in load_items(FIXTURES, only=["wztc-fx-005"])] == ["wztc-fx-005"]
    assert len(load_items(FIXTURES, limit=2)) == 2
    assert load_items(FIXTURES / "nowhere") == []


def test_freeze_and_check_round_trip(tmp_path):
    questions = tmp_path / "q"
    questions.mkdir()
    (questions / "wztc.json").write_text((FIXTURES / "wztc.json").read_text(encoding="utf-8"), encoding="utf-8")
    hash_file = tmp_path / "LOCKED.sha256"
    args = type("Args", (), {"questions": str(questions), "hash_file": str(hash_file)})
    assert check_command(args) == 1  # nothing frozen yet
    assert freeze_command(args) == 0
    assert "items = 3" in hash_file.read_text(encoding="utf-8")
    assert check_command(args) == 0
    # Editing a tuning item changes nothing; editing a locked item's gold value is caught.
    data = json.loads((questions / "wztc.json").read_text(encoding="utf-8"))
    data["items"][2]["note"] = "tuning items may change"
    (questions / "wztc.json").write_text(json.dumps(data), encoding="utf-8")
    assert check_command(args) == 0
    data["items"][0]["expected"]["value"] = "27.43"
    (questions / "wztc.json").write_text(json.dumps(data), encoding="utf-8")
    assert check_command(args) == 1
    assert main(["check", "--questions", str(questions), "--hash-file", str(hash_file)]) == 1


def test_canonical_json_is_order_independent():
    a = [{"id": "b", "x": 1, "_file": "f"}, {"id": "a", "x": 2}]
    assert canonical_json(a) == canonical_json(list(reversed(a))) == '[{"id":"a","x":2},{"id":"b","x":1}]'
    assert locked_digest([dict(a[0], split="locked")]) == locked_digest([dict(a[0], split="locked", _division="w")])


def _bad(**changes):
    item = dict(load_items(FIXTURES)[0], **changes)
    return validate_items([item])


def test_validator_rejects_bad_items():
    assert _bad(type="chart") and "type" in _bad(type="chart")[0]
    assert "split" in _bad(split="tuning")[0]  # page 37 hashes to locked
    assert "refuse" in _bad(refuse=True)[0]
    assert "expected.source" in _bad(expected=dict(ITEM["expected"], source="20220713 NCDOT UAM Ver 2-0.pdf"))[0]
    assert "pdf_pages" in _bad(expected=dict(ITEM["expected"], pdf_pages=[0]))[0]
    assert "pdf_pages" in _bad(expected=dict(ITEM["expected"], pdf_pages=["37"]))[0]
    assert "asker" in _bad(asker="roadway")[0]
    assert "division" in _bad(division="roadway")[0]
    assert "missing keys" in _bad(**{"question": None})[0] or "question" in _bad(question="")[0]
    assert "unknown keys" in _bad(answer="x")[0]
    duplicate = load_items(FIXTURES)[:1] * 2
    assert any("duplicate id" in e for e in validate_items(duplicate))
    unanswerable = dict(NEGATIVE, question="Who won?")
    assert validate_items([dict(unanswerable, split=split_of(unanswerable), type="table")]) == []
    assert "unanswerable" in validate_items([dict(load_items(FIXTURES)[0], type="unanswerable")])[0]
    item = dict(load_items(FIXTURES)[0])
    del item["expected"]
    assert "missing keys" in validate_items([item])[0]


# --- the runner's report ------------------------------------------------------------------

class _Chunk(dict):
    pass


class _Hit:
    def __init__(self, score, chunk):
        self.score, self.chunk = score, chunk


class _FakeRetriever:
    def retrieve(self, question, division, k=5, timer=None, candidates=None, sources=None):
        return [_Hit(2.0, {"source": TMP, "page": 37, "printed_page": "13"}), _Hit(1.0, {"source": TMP, "page": 1})]


def _fake_runtime():
    runtime = Runtime.__new__(Runtime)
    runtime.settings = type("S", (), {"top_k": 5})
    runtime.retriever = _FakeRetriever()
    return runtime


def test_runtime_retrieval_reports_the_ranked_pages():
    retrieval = _fake_runtime().retrieval(ITEM)
    assert retrieval["ranked"][0] == {"source": TMP, "page": 37, "printed_page": "13", "section": None, "score": 2.0}
    assert retrieval["retrieval_ms"] == 0


def test_report_json_and_markdown_are_written(tmp_path):
    items = load_items(FIXTURES)
    retrievals = {i["id"]: _fake_runtime().retrieval(i) for i in items}
    records = {"wztc-fx-001": {"answer": _payload(sources=[_source(37)]), "timing_ms": {"total": 2500}},
               "wztc-fx-004": {"answer": None, "error": "That took too long to answer. Please ask again.", "timing_ms": None}}
    rows = score_rows(items, retrievals, records)
    meta = {"git_commit": "abc123", "git_dirty": False, "index": {"path": "hosted/index", "chunks": 3, "bytes": 1000,
            "sha256_12": "deadbeef0000"}, "settings": {"models": ["m:free"], "request_budget_seconds": 55},
            "split": "all", "stage": "all", "questions": str(FIXTURES)}
    report = build_report("unit", items, rows, meta, stopped="daily limit")
    assert report["coverage"] == {"items": 5, "retrieval_run": 5, "answer_run": 1, "errors": 1, "stopped": "daily limit"}
    # The fake ranks TMP p.37 first for every question: a hit for fx-001 only, a miss for the other two answerable items.
    assert report["aggregates"]["all"]["metrics"]["hit1"] == {"k": 1, "n": 3, "rate": pytest.approx(1 / 3), "ci": list(wilson(1, 3))}
    json_path, md_path = write_outputs(report, tmp_path / "out")
    assert json.loads(json_path.read_text(encoding="utf-8"))["label"] == "unit"
    text = md_path.read_text(encoding="utf-8")
    assert "# Locked set run: unit" in text and "| strict_ok | 1/1 (21-100%) |" in text
    assert "stopped early: daily limit" in text and "### Edge case" in text and "| landscape |" in text
    assert render_markdown(report).startswith("# Locked set run")


def test_cached_answer_is_tied_to_the_question_wording(tmp_path):
    cache = Cache(tmp_path / "cache.jsonl")
    item = dict(ITEM, question="What is the deflection?")
    cache.add({"kind": "answer", "id": item["id"], "answer_config": "cfg", "question_sha": question_sha(item),
               "answer": _payload()})
    assert cached_answer(cache, item, "cfg") is not None
    assert cached_answer(cache, dict(item, question="What is the deflection at 50 mph?"), "cfg") is None
    assert cached_answer(cache, item, "other-config") is None


def test_printed_ranges_expand_on_their_trailing_number():
    assert printed_range("13", "15") == {"13", "14", "15"}
    assert printed_range("5-12", "5-14") == {"5-12", "5-13", "5-14"}
    assert printed_range("A-3", None) == {"A-3"}
    assert printed_range("ii", "iv") == {"ii", "iv"}
    assert printed_range("4-9", "5-1") == {"4-9", "5-1"}


def test_preposition_in_is_not_inches():
    assert value_matches("11 ft", None, "Reduce lanes to 11 ft. Keep 11 in the work zone.")
    assert numbers_with_units("set 11 in the zone") == [(11.0, None, "11")]
