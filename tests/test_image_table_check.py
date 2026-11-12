"""Tests for the image/table retrieval test (prototype.image_table_check): captions and the patched index."""

import json
from pathlib import Path

import numpy as np
import pytest

from prototype.image_table_check import captions, grade_answer, load_cases, patched  # puts hosted/ on sys.path
from divrag.index_file import IndexFile

ROOT = Path(__file__).resolve().parent.parent
TWINS = ROOT / "eval" / "twin_table_questions.json"
TMP_MANUAL = "TMP Design Manual (Combined, No Links).pdf"


class _FakeEmbedder:
    def passages(self, texts):
        return np.ones((len(list(texts)), 4), dtype=np.float32) / 2


def _chunk(source, page, text, section=None):
    return {"text": text, "source": source, "page": page, "section": section, "division": "wztc"}


def test_captions_finds_underlined_figure_and_table_titles():
    text = ("|8|Impact Angle|11.1|\n\n<u>Figure 5 – NC-PCB impact design table for CONCRETE pavement</u> \n\n"
            "# <u>TABLE 3 (continued)</u>\nSee Figure 3 for the offsets.\nPart 2: Chapter 5 | Page 14")
    assert captions(text) == ["Figure 5 – NC-PCB impact design table for CONCRETE pavement", "TABLE 3 (continued)"]


def test_patched_replaces_only_the_extracted_pages_in_document_order():
    chunks = [_chunk("a.pdf", 1, "one", "1 Intro"), _chunk("a.pdf", 2, "old two"), _chunk("a.pdf", 4, "four"),
              _chunk("b.pdf", 1, "other document")]
    index = IndexFile("m", chunks, np.arange(16, dtype=np.float32).reshape(4, 4))
    extracted = [{"division": "wztc", "source": "a.pdf", "page": 2, "text": "new two"},
                 {"division": "wztc", "source": "a.pdf", "page": 3, "text": "scanned three"}]

    result = patched(index, _FakeEmbedder(), extracted)

    assert [(c["source"], c["page"], c["text"]) for c in result.chunks] == [
        ("a.pdf", 1, "one"), ("a.pdf", 2, "new two"), ("a.pdf", 3, "scanned three"), ("a.pdf", 4, "four"),
        ("b.pdf", 1, "other document")]
    assert result.chunks[2]["section"] == "1 Intro"  # the section in effect where the page is
    np.testing.assert_array_equal(result.vectors[0], index.vectors[0])  # kept chunks keep their vectors
    np.testing.assert_array_equal(result.vectors[4], index.vectors[3])


def test_patched_with_captions_starts_each_chunk_with_the_page_caption():
    index = IndexFile("m", [_chunk("a.pdf", 1, "old")], np.ones((1, 4), dtype=np.float32))
    # A table long enough to be split away from the caption under it, as on TMP manual page 38.
    rows = "\n".join(f"|{offset}|Maximum Deflection|{offset + 1.28}|{offset + 2.5}|{offset + 3.75}|"
                     for offset in range(8, 400, 6))
    caption = "Figure 5 – NC-PCB impact design table for CONCRETE pavement"
    text = f"|Offset|Row|30|40|50|\n|---|---|---|---|---|\n{rows}\n\n<u>{caption}</u>"
    result = patched(index, _FakeEmbedder(), [{"division": "wztc", "source": "a.pdf", "page": 1, "text": text}],
                     with_captions=True)
    assert len(result.chunks) > 1
    assert all(caption in c["text"] for c in result.chunks)
    assert result.chunks[0]["text"].startswith(caption + "\n\n|Offset|")


# DAR-669: the asphalt (p.37) and concrete (p.38) NC-PCB deflection tables are twins.

def _twin(case_id):
    return next(c for c in load_cases(TWINS) if c["id"] == case_id)


def _source(page, printed):
    return {"file": TMP_MANUAL, "page": page, "page_end": None, "printed_page": printed}


def test_twin_cases_require_their_own_value_and_reject_the_twins():
    cases = {c["id"]: c for c in load_cases(TWINS)}
    asphalt = cases["wztc-pcb-deflection-asphalt-14ft-40mph"]
    concrete = cases["wztc-pcb-deflection-concrete-14ft-40mph"]
    assert (asphalt["must_contain"], asphalt["must_not_contain"], asphalt["pages"]) == (["27.42"], ["19.42"], [37])
    assert (concrete["must_contain"], concrete["must_not_contain"], concrete["pages"]) == (["19.42"], ["27.42"], [38])
    for case in cases.values():
        assert case["source"] == TMP_MANUAL and case["division"] == "wztc"
        assert not set(case["must_contain"]) & set(case["must_not_contain"])
        assert not set(case["pages"]) & set(case["twin_pages"])


def test_grade_answer_passes_the_right_value_on_the_right_page():
    concrete = _twin("wztc-pcb-deflection-concrete-14ft-40mph")
    assert grade_answer(concrete, "19.42 inches [1]", False, [_source(38, "14")]) == []


def test_grade_answer_fails_a_swapped_value_a_wrong_page_and_a_refusal():
    concrete = _twin("wztc-pcb-deflection-concrete-14ft-40mph")
    # The asphalt table's number, cited to the asphalt page: wrong on every count.
    assert grade_answer(concrete, "27.42 inches [1]", False, [_source(37, "13")]) == [
        "missing 19.42", "has the twin's 27.42", "own page not cited"]
    assert grade_answer(concrete, "19.42 inches [1]", False, [_source(37, "13")]) == ["own page not cited"]
    assert grade_answer(concrete, "", True, []) == ["refused", "missing 19.42", "own page not cited"]
    # Right page by number, but a source whose printed page says otherwise.
    assert grade_answer(concrete, "19.42 inches [1]", False, [_source(38, "13")]) == ["printed page differs"]
    # A merged passage over pages 37-38 shows both printed pages; the number must be the whole value.
    assert grade_answer(concrete, "19.42 inches [1]", False,
                        [{**_source(38, "13"), "printed_page_end": "14"}]) == []
    assert grade_answer(concrete, "119.42 or 19.425 inches [1]", False, [_source(38, "14")]) == ["missing 19.42"]
    other_document = {"file": "Chapter_5.pdf", "page": 38, "page_end": None, "printed_page": "14"}
    assert grade_answer(concrete, "19.42 inches [1]", False, [other_document]) == ["own page not cited"]


@pytest.mark.skipif(not (ROOT / "hosted" / "index" / "chunks.json").is_file(), reason="no committed index")
def test_twin_values_sit_on_their_own_pages_of_the_committed_index():
    """Model-free guard: the numbers the twin cases expect are in the committed chunks of their pages.

    27.42 is also a cell of the concrete table (p.38), so only 19.42 tells the tables apart: it must
    be on p.38 alone, and each page's table chunks must carry that page's own figure caption.
    """
    chunks = json.loads((ROOT / "hosted" / "index" / "chunks.json").read_text(encoding="utf-8"))["chunks"]
    manual = [c for c in chunks if c["source"] == TMP_MANUAL]

    def pages_with(value):
        return {c["page"] for c in manual if value in c["text"]}

    assert 37 in pages_with("27.42")
    assert pages_with("19.42") == {38}
    for page, caption in ((37, "Figure 4"), (38, "Figure 5")):
        table = [c for c in manual if c["page"] == page and ("27.42" in c["text"] or "19.42" in c["text"])]
        assert table and all(caption in c.get("context", "") for c in table)
