"""Tests for the row-label check (DAR-664): rowcheck.py, its hook in the answer and the ROW_GUARD setting."""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.answer import Answerer  # noqa: E402
from divrag.config import load_settings  # noqa: E402
from divrag.divisions import BY_ID  # noqa: E402
from divrag.index_file import Hit  # noqa: E402
from divrag.llm import Completion  # noqa: E402
from divrag.rowcheck import misread_numbers  # noqa: E402

TMP = "TMP Design Manual (Combined, No Links).pdf"
# TMP p.37 as the index holds it: pipe rows with a header row, then the labelled rows.
DEFLECTION = (
    "|**Offset (ft)**|**Impact Angle (degree)/**|**Design Speed(mph)**|**Design Speed(mph)**|\n"
    "|---|---|---|---|\n"
    "|**Offset (ft)**|**Maximum Deflection (in)**|**30**|**40**|\n"
    "|**8**|**Impact Angle**|11.1|10.4|\n"
    "|**8**|**Maximum Deflection**|23.00|25.86|\n"
    "|**14**|**Impact Angle**|12.7|12.1|\n"
    "|**14**|**Maximum Deflection**|25.16|27.42|\n"
    "Rows:\n"
    "Offset (ft)=8 | Impact Angle | Design Speed(mph): 30=11.1, 40=10.4\n"
    "Offset (ft)=8 | Maximum Deflection | Design Speed(mph): 30=23.00, 40=25.86\n"
    "Offset (ft)=14 | Impact Angle | Design Speed(mph): 30=12.7, 40=12.1\n"
    "Offset (ft)=14 | Maximum Deflection | Design Speed(mph): 30=25.16, 40=27.42"
)
# A pipe-only table (no labelled rows): the rows' label is the first cell.
RUNOUT = (
    "|ADT|Runout length (ft)|N (ft)|\n"
    "|---|---|---|\n"
    "|400-1,500|290|5|\n"
    "|800-2,000|330|6|\n"
    "|Over 2,000|360|8|"
)
Q = "What is the maximum deflection at an offset of 14 ft and 40 mph?"


def test_the_value_of_the_named_row_is_not_flagged():
    assert misread_numbers("The maximum deflection is 27.42 in [1].", [DEFLECTION], Q) == []


def test_a_value_from_another_offset_row_is_flagged():
    assert misread_numbers("The maximum deflection is 25.86 in [1].", [DEFLECTION], Q) == ["25.86 in"]


def test_a_value_from_the_other_measure_row_of_the_right_offset_is_flagged_by_its_words():
    assert misread_numbers("It is 12.1 degrees [1].", [DEFLECTION], Q) == ["12.1 deg"]
    assert misread_numbers("The impact angle is 12.1 degrees [1].", [DEFLECTION],
                           "What is the impact angle at an offset of 14 ft and 40 mph?") == []


def test_a_pipe_only_table_is_read_by_the_numbers_in_its_row_labels():
    question = "In Detail 3-2A, what runout length applies with an ADT of 800 to 2,000?"
    assert misread_numbers("The runout length is 330 ft [1].", [RUNOUT], question) == []
    assert misread_numbers("The runout length is 290 ft [1].", [RUNOUT], question) == ["290 ft"]


def test_it_does_not_flag_when_it_cannot_tell():
    # A number in no table row, a passage without a table, a question that names no label of any row,
    # and a number the visitor gave.
    assert misread_numbers("It is 99 in [1].", [DEFLECTION], Q) == []
    assert misread_numbers("It is 25.86 in [1].", ["Offsets under 8 ft need no barrier."], Q) == []
    assert misread_numbers("The maximum is 25.86 in [1].", [DEFLECTION], "How large is the maximum?") == []
    assert misread_numbers("At 14 ft the deflection is 14 ft [1].", [DEFLECTION], Q) == []
    assert misread_numbers("It is 330 ft [1].", [RUNOUT], "What is the runout length?") == []


def test_a_table_reference_in_the_question_is_not_a_row_label():
    # "Table 3-2" must not make the rows labelled 3 or 2 look like the named ones.
    table = "|Zone|Width (ft)|\n|---|---|\n|3|12|\n|4|10|"
    assert misread_numbers("The width is 10 ft [1].", [table], "In Table 3-2, what width does the zone allow?") == []


def test_a_blank_first_cell_takes_the_row_label_above():
    table = "|Offset|Measure|40|\n|---|---|---|\n|14|Angle|12.1|\n||Deflection|27.42|\n|8|Angle|10.4|\n||Deflection|25.86|"
    assert misread_numbers("It is 27.42 in [1].", [table], "What is the deflection at an offset of 14 ft?") == []
    assert misread_numbers("It is 25.86 in [1].", [table], "What is the deflection at an offset of 14 ft?") == ["25.86 in"]


class _LLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def retry_models(self, model):
        return []

    async def complete(self, messages, **kwargs):
        self.calls += 1
        return Completion(self.reply, "test/model:free")


class _Retriever:
    reranker = object()


def _answer(reply, row_guard):
    hits = [Hit(5.0, {"text": DEFLECTION, "source": TMP, "page": 37, "division": "wztc", "section": None})]
    llm = _LLM(reply)
    answerer = Answerer(_Retriever(), llm, row_guard=row_guard)
    return asyncio.run(answerer.answer(Q, BY_ID["utilities"], BY_ID["wztc"], hits, time.monotonic() + 40)), llm


def test_the_guard_flags_a_wrong_row_answer_only_when_on_and_does_not_ask_the_model_again():
    wrong = "The maximum deflection is 25.86 in [1]."
    assert _answer(wrong, row_guard=False)[0].unverified == []
    on, llm = _answer(wrong, row_guard=True)
    assert on.unverified == ["25.86 in"] and on.answer == wrong and not on.refused and on.sources
    assert llm.calls == 1
    assert _answer("The maximum deflection is 27.42 in [1].", row_guard=True)[0].unverified == []


def test_row_guard_setting_defaults_off_and_is_validated():
    assert load_settings({}).row_guard is False
    assert load_settings({"ROW_GUARD": "on"}).row_guard is True
    assert load_settings({"ROW_GUARD": "0"}).row_guard is False
    with pytest.raises(ValueError, match="ROW_GUARD"):
        load_settings({"ROW_GUARD": "maybe"})
