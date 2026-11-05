"""Tests for the number check (DAR-659): normalization, verify.py, and the answer's `unverified` numbers."""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.answer import NOT_FOUND, Answerer, live_step_labels  # noqa: E402
from divrag.divisions import BY_ID  # noqa: E402
from divrag.index_file import Hit  # noqa: E402
from divrag.llm import Completion, LLMError  # noqa: E402
from divrag.numbers import normalize, numbers_with_units  # noqa: E402
from divrag.timing import STEPS, StepTimer  # noqa: E402
from divrag.verify import unverified_numbers  # noqa: E402

TMP = "TMP Design Manual (Combined, No Links).pdf"
# The asphalt deflection table on TMP p.37, as a table chunk reads after U9's labelled rows.
TABLE = (
    "| Offset (ft) | Design speed (mph) | Impact angle | Max deflection (ft) |\n"
    "| 14 | 40 | 12.1 | 27.42 |\n"
    "| 14 | 45 | 11.0 | 31.07 |\n"
    "| 20 | 40 | 15.3 | 22.95 |"
)
QUESTION = "What is the maximum deflection for an offset of 14 ft at a design speed of 40 mph?"


@pytest.mark.parametrize("text, expected", [
    ("12-foot lane", "12 ft lane"), ("12 feet", "12 ft"), ("12 ft.", "12 ft"), ("12'", "12 ft"),
    ('6"', "6 in"), ("6 inches", "6 in"), ("45 mi/h", "45 mph"), ("12 percent", "12 %"), ("30°", "30 deg"),
    ("1,640", "1640"), ("1-1/2", "1.5"), ("1/2", "0.5"), ("12.0", "12"), ("reduce to 11 in the zone", "reduce to 11 in the zone"),
])
def test_numbers_are_normalized_like_the_scorer(text, expected):
    assert normalize(text) == expected


def test_numbers_with_units_reads_value_unit_and_span():
    assert numbers_with_units("a 12-foot lane at 45 MPH, 1-1/2 in. deep") == [
        (12.0, "ft", "12 ft"), (45.0, "mph", "45 mph"), (1.5, "in", "1.5 in")]


def test_a_number_missing_from_the_passages_is_unverified_and_a_present_one_is_not():
    assert unverified_numbers("The maximum deflection is 27.5 ft [1].", [TABLE], QUESTION) == ["27.5 ft"]
    assert unverified_numbers("The maximum deflection is 27.42 ft [1].", [TABLE], QUESTION) == []


def test_twelve_foot_in_the_answer_matches_12_ft_in_the_passage():
    assert unverified_numbers("Lanes must be 12-foot wide [1].", ["Minimum lane width is 12 ft."]) == []
    assert unverified_numbers("Lanes must be 12 feet wide [1].", ["Minimum lane width 12'."]) == []


def test_a_bare_table_cell_verifies_a_number_with_a_unit_but_another_unit_does_not():
    assert unverified_numbers("27.42 ft [1]", ["| 27.42 |"]) == []
    assert unverified_numbers("27.42 ft [1]", ["27.42 in"]) == ["27.42 ft"]


def test_citation_markers_list_numbers_and_the_questions_numbers_are_not_checked():
    answer = "1. At 14 ft and 40 mph [1][2]:\n2. 27.42 ft [1, 3]."
    assert unverified_numbers(answer, ["27.42"], QUESTION) == []
    assert unverified_numbers("At 14 ft and 40 mph [1].", ["27.42"]) == ["14 ft", "40 mph"]


def test_each_missing_number_is_listed_once():
    assert unverified_numbers("27.5 ft or 27.5 ft, or 30 ft.", [TABLE]) == ["27.5 ft", "30 ft"]


class _LLM:
    """Replies one per call (the last repeats); records every call's messages."""

    def __init__(self, *replies):
        self.replies, self.calls, self.models = list(replies), [], []

    def retry_models(self, used):
        return ["test/second:free"]

    def _next(self, messages, models=None):
        self.calls.append(messages)
        self.models.append(models)
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def complete(self, messages, models=None):
        return Completion(self._next(messages, models), models[0] if models else "test/model:free")

    def complete_stream(self, messages, models=None):
        return _Stream(self, messages, models)


class _Stream:
    def __init__(self, llm, messages, models):
        self.llm, self.messages, self.models, self.text = llm, messages, models, ""
        self.model = models[0] if models else "test/model:free"

    def __aiter__(self):
        return self._pieces()

    async def _pieces(self):
        reply = self.llm._next(self.messages, self.models)
        for start in range(0, len(reply), 5):
            yield reply[start:start + 5]
        self.text = reply.strip()


class _Retriever:
    reranker = object()


def _hits():
    return [Hit(5.0, {"text": TABLE, "source": TMP, "page": 37, "division": "wztc", "section": None}),
            Hit(1.0, {"text": "Offsets under 2 ft need no barrier.", "source": TMP, "page": 12, "division": "wztc"})]


def _ask(llm, seconds_left=None, stream=False, timer=None):
    answerer = Answerer(_Retriever(), llm)
    deadline = None if seconds_left is None else time.monotonic() + seconds_left
    events = []
    if stream:
        run = answerer.answer_stream(QUESTION, BY_ID["utilities"], BY_ID["wztc"], _hits(),
                                     lambda event, data: events.append((event, data)), deadline, timer)
    else:
        run = answerer.answer(QUESTION, BY_ID["utilities"], BY_ID["wztc"], _hits(), deadline, timer)
    return asyncio.run(run), events


def test_a_correct_number_is_not_flagged_and_the_model_is_asked_once():
    llm = _LLM("At a 14 ft offset and 40 mph, the maximum deflection is 27.42 ft [1].")
    result, _ = _ask(llm)
    assert result.unverified == [] and result.as_dict()["unverified"] == []
    assert len(llm.calls) == 1


def test_a_wrong_number_is_asked_again_and_the_corrected_answer_replaces_it():
    llm = _LLM("The maximum deflection is 27.5 ft [1].",
               "Row offset 14 ft, column 40 mph, Max deflection (ft): 27.42 ft (PDF page 37) [1].")
    timer = StepTimer()
    result, _ = _ask(llm, timer=timer)

    assert len(llm.calls) == 2
    again = llm.calls[1]
    assert again[-2] == {"role": "assistant", "content": "The maximum deflection is 27.5 ft [1]."}
    assert "27.5 ft" in again[-1]["content"] and "row label" in again[-1]["content"]
    assert "27.42 ft" in result.answer and result.unverified == []
    assert "recheck" in STEPS and timer.as_ms()["recheck"] >= 0


def test_the_first_answer_stays_flagged_when_the_second_is_no_better():
    llm = _LLM("The maximum deflection is 27.5 ft [1].", "It is 28 ft [1].")
    result, _ = _ask(llm)
    assert result.unverified == ["27.5 ft"] and result.answer == "The maximum deflection is 27.5 ft [1]."
    assert result.as_dict()["unverified"] == ["27.5 ft"]


def test_the_recheck_asks_the_model_that_wrote_the_answer():
    llm = _LLM("The maximum deflection is 27.5 ft [1].", "27.42 ft [1].")
    asyncio.run(Answerer(_Retriever(), llm).answer(QUESTION, BY_ID["utilities"], BY_ID["wztc"], _hits()))
    assert llm.models == [None, ["test/model:free", "test/second:free"]]


def test_quoted_labels_ordinals_and_times_are_not_read_as_inches_or_values():
    answer = 'In the row "14" and the column "40 mph", the 2nd value from 8:00 is 27.42 ft [1].'
    assert unverified_numbers(answer, ["Offset 14 ft | 40 | 27.42"]) == []


def test_a_page_number_verifies_a_bare_number_but_not_a_measurement():
    assert unverified_numbers("See PDF page 12 [1].", ["Lanes are 11 ft."], labels=["TMP, PDF page 12"]) == []
    assert unverified_numbers("Lanes are 12 ft [1].", ["Lanes are 11 ft."], labels=["TMP, PDF page 12"]) == ["12 ft"]


def test_numbers_from_earlier_questions_count_as_the_visitors():
    llm = _LLM("At a 3 ft clearance, 27.42 ft [1].")
    history = [{"question": "What if the clearance is 3 ft?", "answer": "An answer [1]."}]
    result = asyncio.run(Answerer(_Retriever(), llm).answer(QUESTION, BY_ID["utilities"], BY_ID["wztc"], _hits(),
                                                           history=history))
    assert result.unverified == [] and len(llm.calls) == 1


@pytest.mark.parametrize("second", [NOT_FOUND, "It is 27.42 ft.", LLMError("busy", status=429)])
def test_the_first_answer_is_kept_flagged_when_the_second_refuses_cites_nothing_or_fails(second):
    llm = _LLM("The maximum deflection is 27.5 ft [1].", second)
    result, _ = _ask(llm)
    assert result.answer == "The maximum deflection is 27.5 ft [1]."
    assert result.unverified == ["27.5 ft"] and not result.refused


def test_no_second_call_when_too_little_time_is_left():
    llm = _LLM("The maximum deflection is 27.5 ft [1].")
    result, _ = _ask(llm, seconds_left=5)
    assert len(llm.calls) == 1 and result.unverified == ["27.5 ft"]


def test_an_uncited_answer_is_checked_against_every_passage():
    result, _ = _ask(_LLM("The maximum deflection is 28 ft."), seconds_left=5)
    assert result.uncited and result.unverified == ["28 ft"]


def test_an_uncited_answer_whose_number_only_one_passage_holds_is_cited_to_it():
    result, _ = _ask(_LLM("The maximum deflection is 27.42 ft."), seconds_left=5)
    assert not result.uncited and result.citation_fix == "number_match" and result.unverified == []
    assert result.answer == "The maximum deflection is 27.42 ft [1]."


def test_the_streamed_done_answer_carries_the_unverified_numbers():
    llm = _LLM("The maximum deflection is 27.5 ft [1].", "It is 28 ft [1].")
    result, events = _ask(llm, stream=True)
    assert ("replace", {"text": ""}) in events  # the second answer is written over the first
    assert result.as_dict()["unverified"] == ["27.5 ft"]


def test_the_recheck_step_has_a_label():
    assert live_step_labels(BY_ID["wztc"], 10, 5)["recheck"] == "Checking the numbers against the source…"
