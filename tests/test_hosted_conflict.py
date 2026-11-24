"""Tests for answers when documents disagree (DAR-674): both values are named with their levels and citations."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag import conflict as conflict_module  # noqa: E402
from divrag.answer import Answerer, _compare_question, _numbered, passage_text  # noqa: E402
from divrag.divisions import BY_ID  # noqa: E402
from divrag.index_file import Hit  # noqa: E402
from divrag.llm import Completion, LLMError  # noqa: E402

MUTCD = "part6.pdf"
DRAWINGS = "Division 11 Combined.pdf"
TMP = "TMP Design Manual (Combined, No Links).pdf"
QUESTION = "What buffer space length does Table 6B-2 give for 50 mph?"
FIRST = "The longitudinal buffer space at 50 mph is 240 ft [2]."


def _hit(source, page, text, score=1.0):
    return Hit(score, {"text": text, "source": source, "page": page, "section": None, "division": "wztc"})


def _hits():
    return [
        _hit(MUTCD, 11, "Table 6B-2. Stopping Sight Distance as a Function of Speed. Speed 50 mph: 425 feet."),
        _hit(DRAWINGS, 30, "Longitudinal buffer space. Posted speed 50 mph: buffer length 240 ft."),
    ]


def _reply(values, recommendation="Follow the MUTCD's 425 ft [1]: the question names its Table 6B-2."):
    return json.dumps({"values": [{"passage": n, "value": v} for n, v in values], "recommendation": recommendation})


class _LLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def retry_models(self, used):
        return ["test/second:free"]

    async def complete(self, messages, models=None):
        self.calls.append(messages)
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return Completion(reply, "test/model")


class _Retriever:
    reranker = None


def _ask(replies, hits=None, **options):
    llm = _LLM(replies)
    answerer = Answerer(_Retriever(), llm, retry_min_score=None, conflict_check=True, **options)
    result = asyncio.run(answerer.answer(QUESTION, BY_ID["wztc"], BY_ID["wztc"], hits or _hits()))
    return result, llm


def test_two_documents_that_disagree_are_both_named_with_level_value_and_citation():
    result, llm = _ask([FIRST, _reply([(1, "425 ft"), (2, "240 ft")])])

    assert len(llm.calls) == 2
    text = result.answer
    # The answer's own citation is renumbered first, then the block's.
    assert text.startswith("The longitudinal buffer space at 50 mph is 240 ft [1].")
    assert "- Federal, MUTCD 11th Edition (December 2023), Part 6: Temporary Traffic Control: 425 ft [2]" in text
    assert "- State, NCDOT 2024 Roadway Standard Drawings, Division 11" in text and ": 240 ft [1]" in text
    assert "**Recommendation** (the assistant's judgment, not an NCDOT rule): Follow the MUTCD's 425 ft [2]" in text
    assert [(s.n, s.title.split(",")[0], s.level, s.level_label) for s in result.sources] == [
        (1, "NCDOT 2024 Roadway Standard Drawings", "state", "State"),
        (2, "MUTCD 11th Edition (December 2023)", "federal", "Federal"),
    ]
    payload = result.as_dict()
    assert payload["conflict"]["by"] == "model"
    assert [(v["level_label"], v["value"]) for v in payload["conflict"]["values"]] == [
        ("Federal", "425 ft"), ("State", "240 ft")]
    assert payload["sources"][1]["level_label"] == "Federal" and payload["sources"][1]["binding"] == "rule"


def test_the_comparison_sees_each_passage_with_its_level():
    _, llm = _ask([FIRST, "NO_CONFLICT"])

    prompt = llm.calls[1][-1]["content"]
    assert "[1] (Federal · MUTCD 11th Edition" in prompt
    assert "[2] (State · NCDOT 2024 Roadway Standard Drawings" in prompt
    assert "Documents in these passages: Federal · MUTCD 11th Edition" in prompt
    assert FIRST not in prompt  # shown the answer, the free models only repeated its value


def test_no_disagreement_leaves_the_answer_as_it_was():
    result, llm = _ask([FIRST, "NO_CONFLICT"])

    assert len(llm.calls) == 2
    assert result.answer == "The longitudinal buffer space at 50 mph is 240 ft [1]."
    assert result.conflict is None and result.as_dict()["conflict"] is None


def test_a_failed_comparison_keeps_the_answer():
    result, _ = _ask([FIRST, LLMError("busy", "BUSY")])

    assert result.answer == "The longitudinal buffer space at 50 mph is 240 ft [1]." and result.conflict is None


def test_passages_from_one_document_or_an_answer_without_numbers_are_not_compared():
    one_document = [_hit(DRAWINGS, 30, "Buffer 50 mph: 240 ft."), _hit(DRAWINGS, 31, "Buffer 60 mph: 360 ft.")]
    _, llm = _ask([FIRST.replace("[2]", "[1]"), "should not be asked"], hits=one_document)
    assert len(llm.calls) == 1

    _, llm = _ask(["A buffer space is required [1].", "should not be asked"])
    assert len(llm.calls) == 1


def test_the_check_is_off_unless_configured():
    llm = _LLM([FIRST, "should not be asked"])
    asyncio.run(Answerer(_Retriever(), llm, retry_min_score=None).answer(QUESTION, BY_ID["wztc"], BY_ID["wztc"],
                                                                          _hits()))
    assert len(llm.calls) == 1


def test_a_value_its_passage_does_not_hold_is_dropped_and_one_value_left_is_no_disagreement():
    result, _ = _ask([FIRST, _reply([(1, "500 ft"), (2, "240 ft")])])

    assert result.conflict is None and "Recommendation" not in result.answer


def test_two_values_that_are_the_same_are_no_disagreement():
    hits = _hits()
    hits[1] = _hit(DRAWINGS, 30, "Posted speed 50 mph: buffer length 425 feet.")
    result, _ = _ask(["The buffer at 50 mph is 425 ft [1].", _reply([(1, "425 ft"), (2, "425 feet")])], hits=hits)

    assert result.conflict is None


def test_document_precedence_writes_the_recommendation_when_it_picks_one_level():
    result, _ = _ask([FIRST, _reply([(1, "425 ft"), (2, "240 ft")], "Follow the NCDOT drawing [2].")],
                     precedence=("state", "federal"))

    assert result.conflict.by == "precedence"
    assert ("**Recommendation** (from the configured document precedence, not a reading of the passages): "
            "Follow the State document, NCDOT 2024 Roadway Standard Drawings") in result.answer
    assert "240 ft [1]. The order is State, then Federal." in result.answer
    assert "Follow the NCDOT drawing" not in result.answer


def test_precedence_that_cannot_choose_keeps_the_models_recommendation():
    hits = [_hit(DRAWINGS, 30, "Buffer at 50 mph: 240 ft."), _hit(TMP, 40, "Buffer at 50 mph: 300 ft.")]
    reply = _reply([(1, "240 ft"), (2, "300 ft")], "Use the TMP manual [2].")
    result, _ = _ask(["The buffer at 50 mph is 240 ft [1].", reply], hits=hits, precedence=("federal",))

    # Both are below every listed level: the order can't choose between them.
    assert result.conflict.by == "model" and "Use the TMP manual" in result.answer


def test_parse_salvages_values_from_a_reply_that_is_almost_json():
    # Nemotron 3.5 Super's reply: the recommendation inside the values list, passages as "[n]".
    reply = ('{"values": [{"document": "MUTCD", "passage": "[1]", "value": "425 feet"}, '
             '{"document": "NCDOT", "passage": 2, "value": "240 ft"}, "recommendation": "Follow the MUTCD [1]."}]')
    found = conflict_module.parse(reply, _hits(), passage_text)
    assert [(v.n, v.value) for v in found.values] == [(1, "425 feet"), (2, "240 ft")]
    assert found.recommendation == "Follow the MUTCD [1]."


def test_documents_with_no_value_are_left_out():
    reply = json.dumps({"values": [{"document": "MUTCD", "passage": None, "value": None},
                                   {"document": "NCDOT", "passage": 2, "value": "240 ft"}], "recommendation": ""})
    assert conflict_module.parse(reply, _hits(), passage_text) is None


def test_parse_reads_json_wrapped_in_text_and_rejects_bad_passage_numbers():
    hits = _hits()
    reply = "Here it is:\n```json\n" + _reply([(1, "425 ft"), (2, "240 ft"), (9, "1 ft")]) + "\n```"
    found = conflict_module.parse(reply, hits, passage_text)
    assert [v.n for v in found.values] == [1, 2]

    assert conflict_module.parse("not json", hits, passage_text) is None
    assert conflict_module.parse("NO_CONFLICT", hits, passage_text) is None


def test_numbered_passages_name_their_level_only_when_asked():
    assert "Federal ·" not in _numbered(_hits())
    assert _numbered(_hits(), levels=True).startswith("[1] (Federal · MUTCD")


def test_a_follow_up_is_compared_with_the_question_it_follows():
    history = [{"question": "What buffer length does Table 6B-2 give for 45 mph?", "answer": "360 feet [1]."}]
    asked = _compare_question("And at 50 mph?", history)
    assert asked.startswith("And at 50 mph?") and "Table 6B-2" in asked
    assert _compare_question("And at 50 mph?", []) == "And at 50 mph?"
