"""Tests for the evaluation harness's grader (pure: no index, no LLM)."""

import importlib.util
from pathlib import Path

import pytest

from rag.index import Hit

_PATH = Path(__file__).resolve().parent.parent / "eval" / "run_eval.py"
_spec = importlib.util.spec_from_file_location("run_eval", _PATH)
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)

CASES = {case["id"]: case for case in run_eval.load_cases()}

# The grader also takes refusal cases (no pages, refusal phrasings to accept, invented answers to reject).
# The question set has none since DAR-678 dropped the old IT refusal probe, so this one is inline.
NOT_COVERED = {
    "id": "R1",
    "question": "What is the toll rate on the I-77 Express Lanes?",
    "refusal": True,
    "accept": [["not contain"], ["doesn't cover"], ["no information"]],
    "reject": [["toll is"], ["per mile"], ["cents"]],
    "source": None,
    "pages": [],
    "note": "No document covers toll rates; the answer must say so and must not invent a rate.",
}


def test_cases_file_is_well_formed():
    assert len(CASES) == 13
    assert sum(bool(c.get("holdout")) for c in CASES.values()) == 5
    for case in CASES.values():
        assert case["question"] and case["note"]
        assert case["accept"] and all(group for group in case["accept"])
    assert not any(c.get("refusal") for c in CASES.values())


@pytest.mark.parametrize("case_id, answer", [
    ("Q1", "For 55 mph the example clear-zone width is **23 ft** (7 m)."),
    ("Q1", "It is 23 feet."),
    ("Q2", "The recommended width is 13 ft."),
    ("Q3", "Florida: drop-off depth > 3 inches, located within 1 2 feet, project duration > 1 day."),
    ("Q4", "New York, Ohio and Texas require a drop-off depth greater than 2 feet."),
    ("Q5", "The curve correction factor is 1.3."),
    ("Q6", "The smallest radius at 70 mph is 1,640 ft."),
    ("Q7", "The clear zone is 20 – 22 ft."),
    ("Q8", "Between 24 and 28 feet."),
    ("H1", "The correction factor is 1.4."),
    ("H2", "The clear zone is 16 - 18 feet."),
    ("H3", "Use a run-out length of 425 ft."),
    ("H4", "California: drop-off depth > 6 inches, located within 8 feet of the travel way."),
    ("H5", "The run-out length is 215 ft."),
])
def test_correct_answers_pass(case_id, answer):
    assert run_eval.grade(answer, CASES[case_id])


@pytest.mark.parametrize("case_id, answer", [
    ("Q1", "The clear-zone width is 30 ft."),
    ("Q2", "The width is 113 ft."),  # '13 f' must start a word
    ("Q3", "Florida uses drop-off depth > 3 inches within 12 feet."),  # missing the duration
    ("Q4", "New York and Ohio."),
    ("Q5", "The factor is 1.2."),
    ("Q7", "The clear zone is 22-24 ft."),
])
def test_wrong_answers_fail(case_id, answer):
    assert not run_eval.grade(answer, CASES[case_id])


def test_sources_trailer_is_not_graded():
    answer = "I can't find that in the context.\n\n**Sources:** `TMP Design Manual.pdf` p.59 23 ft"
    assert not run_eval.grade(answer, CASES["Q1"])


def test_mid_answer_source_line_is_graded():
    answer = "Per the manual:\n**Source:** Table 9-1\n\nThe clear zone is 23 ft."
    assert run_eval.grade(answer, CASES["Q1"])


def test_refusal_passes():
    assert run_eval.grade("The context does not contain the I-77 Express Lanes toll rate.", NOT_COVERED)


def test_invented_answer_is_not_a_refusal():
    assert not run_eval.grade("The toll is 50 cents per mile at peak hours.", NOT_COVERED)


def test_reject_overrides_accept():
    answer = "The context does not contain it, but the toll is usually 50 cents per mile."
    assert not run_eval.grade(answer, NOT_COVERED)


def test_retrieval_hit_checks_source_and_page():
    case = CASES["Q5"]
    right = Hit(text="", score=1.0, source="TMP Design Manual (Combined, No Links).pdf", metadata={"page_label": "59"})
    wrong_page = Hit(text="", score=1.0, source=right.source, metadata={"page_label": "58"})
    other_doc = Hit(text="", score=1.0, source="Chapter_2.pdf", metadata={"page_label": "59"})
    assert run_eval.retrieval_hit([wrong_page, right], case) is True
    assert run_eval.retrieval_hit([wrong_page, other_doc], case) is False
    assert run_eval.retrieval_hit([right], NOT_COVERED) is None


@pytest.mark.parametrize("case_id, answer", [
    ("Q1", "The clear-zone width is 23 meters."),
    ("Q2", "It is 13 meters or 13 feet."),
    ("H1", "The factor is 1.3."),
    ("H3", "Use 475 ft."),
])
def test_wrong_or_hedged_answers_fail(case_id, answer):
    assert not run_eval.grade(answer, CASES[case_id])


def test_quoted_table_rows_are_not_graded():
    answer = "|RADIUS [ft] \\ DESIGN SPEED [mph]|40|45|50|\n|950|1.2|1.3|1.4|\nIn the 50 mph column the factor is 1.4 [1]."
    assert run_eval.grade(answer, CASES["H1"])
