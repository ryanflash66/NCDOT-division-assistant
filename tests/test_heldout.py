"""Tests for the held-out test set (evaluation/heldout/, DAR-661 and DAR-718): the expected-behaviour field,
list and clarify scoring, the fixed edge-case tags, the wrapper's defaults and the frozen question files."""

from pathlib import Path

import pytest

from evaluation.heldout import EDGE_CASES, HASH_FILE, HELDOUT_DIR, tag_errors
from evaluation.heldout.run import main, with_defaults
from evaluation.locked import load_items, locked_digest
from evaluation.locked.run import read_frozen
from evaluation.locked.score import aggregate, clarify_score, score_item
from evaluation.locked.validate import validate_items

TMP = "TMP Design Manual (Combined, No Links).pdf"
TMP_URL = "https://connect.ncdot.gov/projects/WZTC/Documents/TMP%20Design%20Manual%20%28Combined%2C%20No%20Links%29.pdf"
DIVISIONS = {"wztc": {TMP}, "utilities": set(), "tmsd": set()}


def _item(**changes):
    item = {"id": "wztc-h001", "division": "wztc", "asker": "utilities", "type": "table", "edge_cases": [],
            "question": "What taper length applies?", "refuse": False, "split": "tuning", "behaviour": "answer",
            "expected": {"source": TMP, "pdf_pages": [23], "printed_pages": ["4"], "value": "200 ft"}}
    item.update(changes)
    return item


def _payload(text, page=23, refused=False, uncited=False):
    sources = [] if (uncited or refused) else [{"title": None, "url": f"{TMP_URL}#page={page}", "page": page, "page_end": None}]
    return {"answer": text, "refused": refused, "uncited": uncited, "sources": sources, "model": "m:free"}


# --- the expected-behaviour field -----------------------------------------------------------

def test_behaviour_must_be_known_and_fit_refuse():
    assert validate_items([_item()], DIVISIONS) == []
    assert "is not one of" in validate_items([_item(behaviour="guess")], DIVISIONS)[0]
    assert "does not fit refuse false" in validate_items([_item(behaviour="refuse")], DIVISIONS)[0]
    refusal = _item(type="unanswerable", refuse=True, expected=None, behaviour="correct",
                    question="How many moons does Mars have?", split="locked")
    assert "does not fit refuse true" in validate_items([refusal], DIVISIONS)[0]
    assert validate_items([dict(refusal, behaviour="refuse")], DIVISIONS) == []


def test_clarify_needs_the_value_of_each_branch():
    clarify = _item(behaviour="clarify")
    assert "needs expected.all_of" in validate_items([clarify], DIVISIONS)[0]
    clarify["expected"] = dict(clarify["expected"], all_of=["200 ft", ["320 ft", "320 feet"]])
    assert validate_items([clarify], DIVISIONS) == []
    clarify["expected"]["all_of"] = ["200 ft", []]
    assert "expected.all_of must be" in validate_items([clarify], DIVISIONS)[0]


# --- scoring ----------------------------------------------------------------------------------

LIST_ITEM = _item(expected={"source": TMP, "pdf_pages": [23, 24], "printed_pages": ["4", "5"], "value": "cones",
                            "all_of": ["cones", "drums", ["Type III barricades", "Type 3 barricades"]]})


def test_a_list_is_right_only_when_every_part_is_in_the_answer():
    whole = score_item(LIST_ITEM, None, _payload("Use cones, drums and Type 3 barricades [1].", page=24))
    assert whole["value_ok"] and whole["strict_ok"] and whole["critical"] is False
    # The list runs over the page break and the answer stops at the first page: the failure the case is about.
    cut = score_item(LIST_ITEM, None, _payload("Use cones and drums [1]."))
    assert cut["value_ok"] is False and cut["critical"] is True


CLARIFY = _item(behaviour="clarify", expected={"source": TMP, "pdf_pages": [23], "printed_pages": ["4"],
                                               "value": "200 ft", "all_of": ["200 ft", "320 ft"]})


@pytest.mark.parametrize("answer, ok, picked", [
    ("It is 200 ft on asphalt and 320 ft on concrete [1].", True, False),
    ("Which pavement type is it, asphalt or concrete?", True, False),
    ("That depends on the pavement type [1].", True, False),
    ("The length is 200 ft [1].", False, True),            # a default picked silently
    ("The manual gives a length for it [1].", False, False),  # neither shows the branches nor asks
])
def test_clarify_score(answer, ok, picked):
    assert clarify_score(CLARIFY["expected"]["all_of"], answer) == (ok, picked)


def test_a_clarify_item_has_no_value_score_and_a_picked_branch_with_a_citation_is_critical():
    both = score_item(CLARIFY, None, _payload("It is 200 ft on asphalt and 320 ft on concrete [1]."))
    assert both["clarify_ok"] is True and both["value_ok"] is None and both["strict_ok"] is None
    assert both["critical"] is False and both["cited_page_ok_pdf"] is True and both["behaviour"] == "clarify"
    picked = score_item(CLARIFY, None, _payload("The length is 200 ft [1]."))
    assert picked["clarify_ok"] is False and picked["critical"] is True
    assert score_item(CLARIFY, None, _payload("The length is 200 ft.", uncited=True))["critical"] is False
    refused = score_item(CLARIFY, None, _payload("", refused=True))
    assert refused["clarify_ok"] is False and refused["over_refusal"] is True and refused["value_ok"] is None


def test_clarify_items_stay_out_of_the_value_rate():
    items = [_item(), CLARIFY | {"id": "wztc-h002"}]
    rows = [score_item(items[0], None, _payload("It is 200 ft [1].")),
            score_item(items[1], None, _payload("The length is 200 ft [1]."))]
    metrics = aggregate(rows, items)["all"]["metrics"]
    assert (metrics["value_ok"]["k"], metrics["value_ok"]["n"]) == (1, 1)
    assert (metrics["clarify_ok"]["k"], metrics["clarify_ok"]["n"]) == (0, 1)
    assert (metrics["critical"]["k"], metrics["critical"]["n"]) == (1, 2)


# --- tags and the wrapper ----------------------------------------------------------------------

def test_the_32_matrix_rows_each_have_one_tag():
    numbers = sorted(number for number, _ in EDGE_CASES.values() if number)
    assert numbers == list(range(1, 33))


def test_unknown_tags_are_reported():
    assert tag_errors([_item(edge_cases=["rotated", "scan"])]) == []
    assert "rotated_text" in tag_errors([_item(edge_cases=["rotated_text"], _file="wztc.json")])[0]


def test_wrapper_adds_the_heldout_paths_and_keeps_given_ones():
    argv = with_defaults(["--label", "x", "--out", "elsewhere"])
    assert argv[0] == "run" and argv[argv.index("--questions") + 1] == str(HELDOUT_DIR)
    assert argv[argv.index("--out") + 1] == "elsewhere" and "--runs-file" in argv and "--cache" in argv
    assert with_defaults(["check"])[1:] == ["--questions", str(HELDOUT_DIR), "--hash-file", str(HASH_FILE)]


def test_wrapper_stops_on_an_unknown_tag(tmp_path, capsys):
    import json

    (tmp_path / "wztc.json").write_text(json.dumps({"division": "wztc", "items": [_item(edge_cases=["landscape"])]}),
                                        encoding="utf-8")
    assert main(["validate", "--questions", str(tmp_path)]) == 1
    assert "landscape" in capsys.readouterr().out


# --- the committed set ---------------------------------------------------------------------------

def test_the_committed_set_is_valid_and_matches_its_hash():
    items = load_items(HELDOUT_DIR)
    if not items:
        pytest.skip("no held-out question files yet")
    assert validate_items(items) == [] and tag_errors(items) == []
    assert all(item.get("behaviour") for item in items)
    frozen = read_frozen(Path(HASH_FILE))
    assert frozen is not None, "run `py -m evaluation.heldout.run freeze`"
    assert locked_digest(items) == frozen


def test_citation_markers_are_not_read_as_the_value():
    item = _item(expected={"source": TMP, "pdf_pages": [23], "printed_pages": ["4"], "value": "2"})
    assert score_item(item, None, _payload("Three copies are required [2]."))["value_ok"] is False
    assert score_item(item, None, _payload("Submit 2 copies [1]."))["value_ok"] is True


def test_saying_a_section_is_reserved_counts_as_declining():
    reserved = _item(type="unanswerable", refuse=True, expected=None, behaviour="refuse", split="locked",
                     question="What does Subpart C of 23 CFR part 630 require?", accept_reply=["reserved"])
    assert validate_items([reserved], DIVISIONS) == []
    said = score_item(reserved, None, _payload("Subpart C is marked [Reserved]; it has no requirements [1]."))
    assert said["false_answer"] is False and said["critical"] is False
    made_up = score_item(reserved, None, _payload("Subpart C requires a traffic control plan [1]."))
    assert made_up["false_answer"] is True and made_up["critical"] is True
    assert "accept_reply" in validate_items([_item(accept_reply=["reserved"])], DIVISIONS)[0]
