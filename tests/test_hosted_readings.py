"""Tests for the two readings of picture pages and the notice when they disagree (DAR-739)."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag import readings as rd  # noqa: E402
from divrag.answer import (NOT_FOUND, Answer, Answerer, Passages, attach_sources, build_messages,  # noqa: E402
                           passage_text)
from divrag.config import load_settings  # noqa: E402
from divrag.divisions import BY_ID  # noqa: E402
from divrag.index_file import Hit  # noqa: E402
from divrag.llm import Completion  # noqa: E402

APPENDIX = "010604.pdf"  # the Utilities appendix with the scanned Indiana permit (utilities-h056)
INTERSECTIONS = "09. At Grade Intersections.pdf"  # the sideways turn-lane table (tmsd-h052)
PERMIT_OCR = ("The edge of the area after removal shall be such that the maximum variation from the vertical "
              "will not exceed 1/2 inches. The depth shall be a minimum of 9 inches.")
PERMIT_IMAGE = ("The edge of the area after removal shall be such that the maximum variation from the vertical "
                "will not exceed 1 1/2 inches. The depth shall be a minimum of 9 inches.")
SIDEWAYS_OCR = """OCR text (page turned 90 degrees):
North Carolina Highways.  200'  575'  250′  55  60
Manual or Policy on Street  150'  500,  200'  50  55
vehicles should be calculated  100'  300'  150′  45  50"""
SIDEWAYS_IMAGE = """| Posted Speed | Design Speed | Minimum Deceleration Length | Desirable Deceleration Length | Bay Taper |
|---|---|---|---|---|
| 60 | 55 | 250' | 575' | 200' |
| 55 | 50 | 200' | 500' | 150' |
| 50 | 45 | 150' | 300' | 100' |"""


# compare()

def test_a_fraction_ocr_dropped_is_a_disagreement_shown_as_both_readings():
    agreement, differences = rd.compare(PERMIT_OCR, PERMIT_IMAGE)

    assert agreement == rd.DISAGREE
    ((ocr, image),) = differences
    assert "0.5 in" in ocr and "1.5 in" in image


def test_a_sideways_table_read_right_to_left_disagrees_row_by_row():
    agreement, differences = rd.compare(SIDEWAYS_OCR, SIDEWAYS_IMAGE)

    assert agreement == rd.DISAGREE
    assert ("200, 575, 250, 55, 60", "60, 55, 250, 575, 200") in differences
    assert len(differences) == 3


def test_the_same_numbers_spelled_differently_agree():
    # Units spelled out or abbreviated, Markdown around the image reading, a foot mark OCR lost.
    assert rd.compare("Taper 300 feet at 45 mph; offset 12", "**Taper:** 300' at 45 MPH | offset 12 ft") == (rd.AGREE, [])
    # The same rows in the same order agree, whatever words sit between the numbers.
    assert rd.compare("Speed 60 55 250 575 200 row", "| 60 | 55 | 250' | 575' | 200' |")[0] == rd.AGREE


def test_a_value_in_another_unit_disagrees():
    agreement, differences = rd.compare("Clearance 18 in", "Clearance 18 ft")
    assert agreement == rd.DISAGREE and differences


def test_a_page_ocr_found_no_text_on_is_image_only():
    assert rd.compare("", "Bay taper 150'") == (rd.IMAGE_ONLY, [])
    assert rd.compare("<!-- Start of picture text --><!-- End of picture text -->", "3:1")[0] == rd.IMAGE_ONLY


def test_differences_are_capped():
    ocr = " ".join(f"item {n} ft" for n in range(20))
    image = " ".join(f"item {n + 100} ft" for n in range(20))
    agreement, differences = rd.compare(ocr, image)
    assert agreement == rd.DISAGREE and len(differences) == rd.MAX_DIFFERENCES


# page_readings.json

def _file(tmp_path, pages):
    (tmp_path / rd.READINGS_FILE).write_text(json.dumps({"pages": pages}), encoding="utf-8")
    return tmp_path


def _row(agreement, image="read from the image", differences=()):
    return {"image": image, "agreement": agreement, "differences": [list(d) for d in differences]}


def test_readings_load_by_page_and_skip_rows_that_were_not_read(tmp_path):
    readings = rd.load(_file(tmp_path, {"utilities": {APPENDIX: {
        "278": _row(rd.DISAGREE, PERMIT_IMAGE, [("0.5 in", "1.5 in")]),
        "279": _row(rd.AGREE),
        "280": {"image": "", "agreement": "no_image_text"},  # the model saw no text: not a reading to use
        "281": {"agreement": rd.DISAGREE},  # no image text at all
    }}}))

    assert len(readings) == 2
    assert readings.get("utilities", APPENDIX, 278).differs
    assert not readings.get("utilities", APPENDIX, 279).differs
    assert readings.get("utilities", APPENDIX, 280) is None


def test_a_missing_or_broken_file_means_no_readings(tmp_path):
    assert len(rd.load(tmp_path)) == 0
    (tmp_path / rd.READINGS_FILE).write_text("{not json", encoding="utf-8")
    assert len(rd.load(tmp_path)) == 0
    (tmp_path / rd.READINGS_FILE).write_text(json.dumps({"pages": {"utilities": ["x"]}}), encoding="utf-8")
    assert len(rd.load(tmp_path)) == 0


# Answer time

def _chunk(page, text="prose", source=APPENDIX, division="utilities", **extra):
    return {"text": text, "source": source, "page": page, "section": None, "division": division, **extra}


def _readings():
    return rd.Readings({
        ("utilities", APPENDIX, 278): rd.PageReading(278, rd.DISAGREE, PERMIT_IMAGE, (("0.5 in depth", "1.5 in depth"),)),
        ("utilities", APPENDIX, 279): rd.PageReading(279, rd.AGREE, "same as OCR"),
        ("utilities", APPENDIX, 280): rd.PageReading(280, rd.IMAGE_ONLY, "Bay taper 150'"),
    })


def test_only_pages_whose_readings_differ_are_annotated_and_the_index_is_not_touched():
    original = _chunk(278, PERMIT_OCR)
    agreeing = Hit(1.0, _chunk(279))
    hits = [Hit(2.0, original), agreeing, Hit(0.5, _chunk(500))]

    annotated = _readings().annotate(hits)

    assert annotated[0].chunk["readings"][0]["image"] == PERMIT_IMAGE
    assert "readings" not in original  # a copy: the index's chunk is shared by every request
    assert annotated[1] is agreeing and annotated[2] is hits[2]


def test_a_merged_passage_carries_the_readings_of_its_parts_pages():
    merged = Hit(1.0, dict(_chunk(278), parts=[_chunk(278, PERMIT_OCR), _chunk(279), _chunk(280, "x")]))

    (hit,) = _readings().annotate([merged])

    assert [r["page"] for r in rd.passage_readings(hit.chunk)] == [278, 280]


def test_the_model_reads_the_image_reading_after_its_passage_with_a_rule():
    (hit,) = _readings().annotate([Hit(1.0, _chunk(278, PERMIT_OCR))])

    text = passage_text(hit.chunk)
    assert text.startswith(PERMIT_OCR)
    assert "Read from the page image (PDF page 278)" in text and PERMIT_IMAGE in text

    system = build_messages("How far may the edge vary?", BY_ID["utilities"], BY_ID["utilities"], [hit])[0]["content"]
    assert rd.READING_RULE in system
    plain = build_messages("q", BY_ID["utilities"], BY_ID["utilities"], [Hit(1.0, _chunk(279))])[0]["content"]
    assert rd.READING_RULE not in plain


def test_a_cited_page_that_disagrees_gets_both_readings_and_a_notice():
    hits = _readings().annotate([Hit(1.0, _chunk(278, PERMIT_OCR)), Hit(0.5, _chunk(279))])

    text, sources = attach_sources("The edge may vary by at most 1 1/2 inches [1]. Depth 9 inches [2].", hits)
    answer = Answer(text, refused=False, sources=sources)

    first, second = sources
    assert first.readings[0]["agreement"] == rd.DISAGREE and first.readings[0]["image"] == PERMIT_IMAGE
    assert second.readings == ()
    (notice,) = answer.notices()
    assert notice.startswith(f"{first.title}, PDF page 278 is from a low-quality scan")
    assert "“0.5 in depth” in the text vs “1.5 in depth” in the image" in notice
    assert notice.endswith("Check the page before relying on this value.")
    payload = answer.as_dict()
    assert payload["notices"] == [notice] and payload["sources"][0]["readings"][0]["page"] == 278
    # The answer's own text is unchanged: the notice is a field of its own.
    assert payload["answer"] == text


def test_an_image_only_page_gets_a_notice_without_pairs_and_a_refusal_gets_none():
    (hit,) = _readings().annotate([Hit(1.0, _chunk(280, "x"))])
    _, sources = attach_sources("Bay taper is 150 ft [1].", [hit])

    (notice,) = Answer("Bay taper is 150 ft [1].", refused=False, sources=sources).notices()
    assert "could only be read from the page image" in notice
    assert Answer("Not covered.", refused=True, sources=sources).notices() == []


def test_the_notice_names_the_difference_holding_the_answers_number_first():
    reading = {"page": 5, "agreement": rd.DISAGREE,
               "differences": [["width 10 ft", "width 12 ft"], ["taper 0.5 in", "taper 1.5 in"]]}
    notice = rd.notice("Doc, PDF page 5", [reading], "The taper is 1 1/2 in [1].")
    assert notice.index("taper 0.5 in") < notice.index("width 10 ft")


def test_a_narrowed_citation_keeps_only_the_cited_pages_readings():
    merged = Hit(1.0, dict(_chunk(278), parts=[_chunk(278, PERMIT_OCR + " permit edge vertical"),
                                               _chunk(280, "storage bay lane widening taper")]))
    (hit,) = _readings().annotate([merged])

    _, (source,) = attach_sources("The edge may vary from the vertical by 1 1/2 inches [1].", [hit])

    assert source.page == 278 and [r["page"] for r in source.readings] == [278]


class _Retriever:
    reranker = object()
    candidates = 40

    def with_following(self, hits, top=2):
        return hits

    def with_next_page(self, hits):
        return hits

    def as_passages(self, hits):
        return list(hits)


class _LLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def retry_models(self, used):
        return [used]

    async def complete(self, messages, models=None):
        self.calls.append(messages)
        return Completion(self.replies[min(len(self.calls), len(self.replies)) - 1], "gpt-6.1-terra")


def test_the_answerer_reads_the_image_reading_and_warns(tmp_path):
    llm = _LLM(["It may not vary more than 1 1/2 inches from the vertical [1]."])
    answerer = Answerer(_Retriever(), llm, readings=_readings())

    result = asyncio.run(answerer.answer("How far may the edge vary?", BY_ID["utilities"], BY_ID["utilities"],
                                         [Hit(1.0, _chunk(278, PERMIT_OCR))]))

    assert PERMIT_IMAGE in llm.calls[0][1]["content"]
    assert result.notices() and not result.unverified  # 1 1/2 is in the passage's image reading


def test_without_readings_the_answerer_sends_what_it_sent_before():
    llm = _LLM(["At most 1/2 inch [1]."])
    asyncio.run(Answerer(_Retriever(), llm).answer("q", BY_ID["utilities"], BY_ID["utilities"],
                                                   [Hit(1.0, _chunk(278, PERMIT_OCR))]))
    assert "Read from the page image" not in llm.calls[0][1]["content"]


def test_the_second_look_carries_readings_and_does_not_repeat_an_annotated_passage():
    llm = _LLM([NOT_FOUND, "Found it [2]."])
    first = _chunk(278, PERMIT_OCR)
    # The first passage again in `more` (same chunk), and a new image-only page.
    hits = Passages([Hit(2.0, first)], more=[Hit(1.5, first), Hit(1.0, _chunk(280, "x"))])

    result = asyncio.run(Answerer(_Retriever(), llm, readings=_readings()).answer(
        "q", BY_ID["utilities"], BY_ID["utilities"], hits))

    assert result.retried and not result.refused
    second_look = llm.calls[1][-1]["content"]
    assert "[2]" in second_look and "[3]" not in second_look  # page 278 not shown twice
    assert "Bay taper 150'" in second_look


# Settings

def test_page_readings_are_on_by_default_and_can_be_turned_off():
    assert load_settings({}).page_readings is True
    assert load_settings({"PAGE_READINGS": "off"}).page_readings is False
    with pytest.raises(ValueError, match="PAGE_READINGS"):
        load_settings({"PAGE_READINGS": "maybe"})
