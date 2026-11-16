"""Tests for the two-model number agreement check (DAR-663): agreement.py and its hook in the Answerer."""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.agreement import answer_numbers, disagreeing, second_opinion_models  # noqa: E402
from divrag.answer import NOT_FOUND, Answerer, LiveSteps, live_step_labels  # noqa: E402
from divrag.config import load_settings  # noqa: E402
from divrag.divisions import BY_ID  # noqa: E402
from divrag.index_file import Hit  # noqa: E402
from divrag.llm import API_URL, OPENAI_URL, Completion, FallbackClient, LLMError, OpenAIClient, OpenRouterClient  # noqa: E402
from divrag.timing import STEPS, StepTimer  # noqa: E402

TMP = "TMP Design Manual (Combined, No Links).pdf"
# The asphalt deflection table on TMP p.37: 31.07 ft is the neighbouring row's value, on the same page.
TABLE = (
    "| Offset (ft) | Design speed (mph) | Impact angle | Max deflection (ft) |\n"
    "| 14 | 40 | 12.1 | 27.42 |\n"
    "| 14 | 45 | 11.0 | 31.07 |\n"
    "| 20 | 40 | 15.3 | 22.95 |"
)
QUESTION = "What is the maximum deflection for an offset of 14 ft at a design speed of 40 mph?"
RIGHT = "At a 14 ft offset and 40 mph, the maximum deflection is 27.42 ft [1]."
WRONG_CELL = "At a 14 ft offset and 40 mph, the maximum deflection is 31.07 ft [1]."
FIRST, SECOND, THIRD = "test/model:free", "test/second:free", "test/third:free"


def _numbers(text, asked=QUESTION):
    return [raw for _, _, raw in answer_numbers(text, asked)]


# What is compared

def test_page_references_identifiers_citations_and_the_questions_numbers_are_not_compared():
    text = ("Per Table 6-1 and Detail 3-2A, row 14, on p.13 (PDF page 37) of the TMP manual, "
            "at 14 ft and 40 mph the maximum deflection is 27.42 ft [1][2].")
    assert _numbers(text) == ["27.42 ft"]
    assert _numbers("See pp. 12-13 and Section 3.6.") == []


def test_the_same_number_is_listed_once():
    assert _numbers("27.42 ft, that is 27.42 feet [1].") == ["27.42 ft"]


def test_everyday_words_before_a_value_are_not_identifiers():
    assert _numbers("In both cases 500 ft; for all types 36 in [1].", "") == ["500 ft", "36 in"]
    assert _numbers("Use a Type 3 barricade, Case 2 [1].", "") == []


def _compare(first, second, asked=""):
    return disagreeing(answer_numbers(first, asked), answer_numbers(second, asked))


def test_a_wrong_cell_disagrees_and_the_first_answers_number_is_flagged():
    assert _compare(WRONG_CELL, RIGHT, QUESTION) == (["31.07 ft"], ["27.42 ft"])


def test_the_same_value_in_another_spelling_or_unit_agrees():
    assert _compare("It is 12-foot wide [1].", "12 ft [2].") == ([], [])
    # A table cell's bare value matches the same value with its column's unit.
    assert _compare("27.42 ft [1]", "Max deflection: 27.42 [1]") == ([], [])
    assert _compare("A 1.5 ft cover [1].", "An 18 in cover [1].") == ([], [])
    assert _compare("5 ft [1]", "5 in [1]") == (["5 ft"], ["5 in"])


def test_leaving_a_number_out_is_not_a_disagreement():
    assert _compare("Lanes are 12 ft with a 2 ft shoulder [1].", "Lanes are 12 ft [1].") == ([], [])
    assert _compare("Lanes are 12 ft [1].", "Lanes are 12 ft with a 2 ft shoulder [1].") == ([], [])


def test_a_number_of_another_kind_is_no_contradiction():
    assert _compare("The taper is 500 ft, at 45 mph [1].", "The taper is 500 ft with 12 % grade [1].") == ([], [])


def test_one_wrong_number_of_two_is_flagged_alone():
    assert _compare("The N width is 6 ft and the runout length 330 ft [1].",
                    "N width 5 ft; runout length 330 ft [1].") == (["6 ft"], ["5 ft"])


# Which model gives the second opinion

def test_the_second_opinion_comes_from_the_next_free_model_never_the_one_that_answered():
    client = OpenRouterClient("k", [FIRST, SECOND, THIRD])
    assert second_opinion_models(client, FIRST) == [SECOND, THIRD]
    assert second_opinion_models(client, THIRD) == [FIRST, SECOND]  # the last model is checked by the first
    assert second_opinion_models(client, FIRST.removesuffix(":free")) == [SECOND, THIRD]
    # Unknown author: it might be any of them, and it must not check itself.
    assert second_opinion_models(client, "unknown:free") == []
    assert second_opinion_models(OpenRouterClient("k", [FIRST]), FIRST) == []  # one model: no second opinion
    # After a retry, the model that refused is not asked: it would refuse again.
    assert second_opinion_models(client, SECOND, avoid=[FIRST]) == [THIRD]


def test_an_openai_answer_is_checked_by_the_first_free_model_and_openai_never_twice():
    client = FallbackClient(OpenAIClient("sk", ["gpt-6.1-terra"]), OpenRouterClient("k", [FIRST, SECOND]))
    assert second_opinion_models(client, "gpt-6.1-terra") == [FIRST, SECOND]
    assert second_opinion_models(client, FIRST) == [SECOND]  # OpenAI is never asked for a second opinion
    assert second_opinion_models(OpenAIClient("sk", ["gpt-6.1-terra"]), "gpt-6.1-terra") == []


# The check in the Answerer

class _LLM:
    """Replies one per call (the last repeats); records every call's messages and models."""

    models = [FIRST, SECOND, THIRD]

    def __init__(self, *replies):
        self.replies, self.calls, self.asked_models, self.streamed = list(replies), [], [], 0

    def retry_models(self, used):
        return [SECOND]

    def _next(self, messages, models=None):
        self.calls.append(messages)
        self.asked_models.append(models)
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def complete(self, messages, models=None):
        return Completion(self._next(messages, models), models[0] if models else FIRST)

    def complete_stream(self, messages, models=None):
        self.streamed += 1
        return _Stream(self, messages, models)


class _Stream:
    def __init__(self, llm, messages, models):
        self.llm, self.messages, self.models, self.text = llm, messages, models, ""
        self.model = models[0] if models else FIRST

    def __aiter__(self):
        return self._pieces()

    async def _pieces(self):
        reply = self.llm._next(self.messages, self.models)
        for start in range(0, len(reply), 5):
            yield reply[start:start + 5]
        self.text = reply.strip()


class _Retriever:
    reranker = object()

    def retrieve(self, question, division, k=5, candidates=None):
        return []  # a refusal's search for another division finds nothing


def _hits():
    return [Hit(5.0, {"text": TABLE, "source": TMP, "page": 37, "division": "wztc", "section": None}),
            Hit(1.0, {"text": "Offsets under 2 ft need no barrier.", "source": TMP, "page": 12, "division": "wztc"})]


def _ask(llm, agreement=True, seconds_left=None, stream=False, timer=None):
    answerer = Answerer(_Retriever(), llm, number_agreement=agreement)
    deadline = None if seconds_left is None else time.monotonic() + seconds_left
    events = []
    if stream:
        run = answerer.answer_stream(QUESTION, BY_ID["utilities"], BY_ID["wztc"], _hits(),
                                     lambda event, data: events.append((event, data)), deadline, timer)
    else:
        run = answerer.answer(QUESTION, BY_ID["utilities"], BY_ID["wztc"], _hits(), deadline, timer)
    return asyncio.run(run), events


def test_a_wrong_cell_the_second_model_reads_differently_is_flagged_unverified():
    llm = _LLM(WRONG_CELL, RIGHT)
    timer = StepTimer()
    result, _ = _ask(llm, timer=timer)

    assert len(llm.calls) == 2
    assert llm.calls[1] == llm.calls[0]  # the same question and passages, not the first answer
    assert llm.asked_models[1] == [SECOND, THIRD]
    assert result.answer == WRONG_CELL and not result.refused  # flagged, not replaced
    assert result.unverified == ["31.07 ft"]
    payload = result.as_dict()
    assert payload["unverified"] == ["31.07 ft"]
    assert payload["second_opinion"] == {"model": SECOND, "agreed": False, "numbers": ["27.42 ft"],
                                         "disagreed": ["31.07 ft"], "instead": ["27.42 ft"]}
    assert "agree" in STEPS and timer.as_ms()["agree"] >= 0


def test_agreement_leaves_the_answer_as_it_is():
    llm = _LLM(RIGHT, "The maximum deflection is 27.42 feet [1].")
    result, _ = _ask(llm)
    assert len(llm.calls) == 2 and result.unverified == [] and result.answer == RIGHT
    assert result.as_dict()["second_opinion"]["agreed"] is True


def test_after_a_retry_the_model_that_refused_is_not_the_second_opinion():
    llm = _LLM(NOT_FOUND, WRONG_CELL, RIGHT)
    result, _ = _ask(llm)
    assert result.retried and result.model == SECOND
    assert llm.asked_models == [None, [SECOND], [THIRD]]
    assert result.unverified == ["31.07 ft"]


def test_an_answer_with_no_numbers_needs_no_second_call():
    llm = _LLM("A barrier is needed when the drop-off is in the clear zone [1].")
    result, _ = _ask(llm)
    assert len(llm.calls) == 1 and result.as_dict()["second_opinion"] is None


def test_a_refusal_needs_no_second_opinion():
    llm = _LLM(NOT_FOUND)
    result, _ = _ask(llm, seconds_left=5)  # too little time for the retry after a refusal
    assert result.refused and len(llm.calls) == 1


def test_off_by_default_and_when_the_setting_is_off():
    llm = _LLM(WRONG_CELL, RIGHT)
    result = asyncio.run(Answerer(_Retriever(), llm).answer(QUESTION, BY_ID["utilities"], BY_ID["wztc"], _hits()))
    assert len(llm.calls) == 1 and result.unverified == []
    assert load_settings({}).number_agreement is False
    assert load_settings({"NUMBER_AGREEMENT": "on"}).number_agreement is True
    with pytest.raises(ValueError):
        load_settings({"NUMBER_AGREEMENT": "maybe"})


def test_skipped_silently_when_too_little_time_is_left():
    llm = _LLM(WRONG_CELL, RIGHT)
    result, _ = _ask(llm, seconds_left=10)
    assert len(llm.calls) == 1 and result.unverified == [] and result.second_opinion is None


@pytest.mark.parametrize("second", [NOT_FOUND, "The table gives the deflection by offset and speed [1].",
                                    LLMError("busy", status=429)])
def test_a_second_model_that_refuses_states_no_number_or_fails_has_no_opinion(second):
    llm = _LLM(WRONG_CELL, second)
    result, _ = _ask(llm)
    assert len(llm.calls) == 2 and result.unverified == [] and result.second_opinion is None
    assert result.answer == WRONG_CELL


def test_a_number_missing_from_the_passages_and_a_contradicted_one_are_both_flagged_once():
    first = "The maximum deflection is 31.07 ft, about 9.5 m [1]."  # 9.5 is in no passage
    llm = _LLM(first, first, RIGHT)  # the recheck repeats the answer, so it is kept
    result, _ = _ask(llm)
    assert result.unverified == ["9.5", "31.07 ft"]


def test_the_streamed_answer_is_not_replaced_by_the_second_opinion():
    llm = _LLM(WRONG_CELL, RIGHT)
    steps = LiveSteps(live_step_labels(BY_ID["wztc"], 10, 5), lambda event, data: events.append((event, data)))
    events = []
    result, streamed = _ask(llm, stream=True, timer=StepTimer(steps))

    assert ("replace", {"text": ""}) not in streamed  # the text on the page stays the first answer
    assert llm.streamed == 1  # the second opinion is a plain call, never streamed over the answer
    assert result.as_dict()["unverified"] == ["31.07 ft"]
    agree = [data for event, data in events if event == "step" and data["id"] == "agree"]
    assert [d["status"] for d in agree] == ["start", "done"]
    assert agree[0]["label"] == "Asking a second model to check the numbers…"


def test_with_openai_answering_the_second_opinion_goes_to_openrouter_only():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((str(request.url), body.get("model") or body.get("models")))
        if str(request.url) == OPENAI_URL:
            return httpx.Response(200, json={"model": "gpt-6.1-terra-2026", "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                                             "choices": [{"finish_reason": "stop", "message": {"content": WRONG_CELL}}]})
        return httpx.Response(200, json={"model": FIRST,
                                         "choices": [{"finish_reason": "stop", "message": {"content": RIGHT}}]})

    transport = httpx.MockTransport(handler)
    client = FallbackClient(OpenAIClient("sk", ["gpt-6.1-terra"], transport=transport),
                            OpenRouterClient("k", [FIRST, SECOND], transport=transport))
    result, _ = _ask(client)

    assert [url for url, _ in seen] == [OPENAI_URL, API_URL]  # OpenAI once, then the free models
    assert seen[1][1] == [FIRST, SECOND]
    assert result.model == "gpt-6.1-terra" and result.unverified == ["31.07 ft"]
    assert result.second_opinion.model == FIRST
