"""Footnote questions in the hosted app (DAR-717): the note rule in the prompt and the notes tag in the keyword field."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.answer import NOTE_RULE, build_messages  # noqa: E402
from divrag.divisions import BY_ID  # noqa: E402
from divrag.index_file import NOTES_FIELD, Hit, IndexFile, field_text  # noqa: E402

import numpy as np  # noqa: E402

SPECS = "2024 Standard Specifications for Roads and Structures.pdf"
TABLE = ("|Acid Soluble Pigments A|Pigment Content|Property|\n|---|---|---|\n"
         "|ASTM D1135 & D3256|ASTM D3723|Test Method|")
NOTES = "Notes:\nA. Use a 5% acetic acid solution with a pH 4 + 2 to determine solubility."


def _chunk(text, **extra):
    return {"text": text, "source": SPECS, "page": 580, "section": None, "division": "wztc", **extra}


@pytest.mark.parametrize("question", [
    "Per the note to Table 1080-1, what solution is used to determine acid soluble pigments?",
    "Per footnote b of Table 3-1 in the UAM, what is the minimum cover depth?",
    "According to the notes under the barrier chart, what speed limits water-filled barrier?",
    "What does the superscript A on HG-56 Solids mean in Table 1080-2?",
    "Curves flatter than what radius need no adjusted clear zone according to the curve correction note in the "
    "TMP Design Manual?",
])
def test_a_question_naming_a_note_gets_the_note_rule(question):
    system, _ = build_messages(question, BY_ID["wztc"], BY_ID["wztc"], [Hit(1.0, _chunk(f"{TABLE}\n{NOTES}"))])

    assert f"\n8. {NOTE_RULE}" in system["content"]


@pytest.mark.parametrize("question", [
    "What test method is used for pigment content?",
    "Does the manual note a minimum cover depth for HDD under a freeway?",  # "note" as a verb
])
def test_an_ordinary_table_question_gets_the_prompt_it_had_before(question):
    hits = [Hit(1.0, _chunk(f"{TABLE}\n{NOTES}"))]

    system, _ = build_messages(question, BY_ID["wztc"], BY_ID["wztc"], hits)
    plain, _ = build_messages("Q?", BY_ID["wztc"], BY_ID["wztc"], hits)

    assert NOTE_RULE not in system["content"] and system == plain
    assert "\n8. " not in system["content"]


def test_a_chunk_carrying_table_notes_is_tagged_in_the_keyword_field():
    assert NOTES_FIELD in field_text(_chunk(f"{TABLE}\n{NOTES}", notes=True)).split("\n")
    assert NOTES_FIELD not in field_text(_chunk(TABLE))


def test_a_footnote_question_ranks_the_table_with_its_notes_first():
    # Two chunks name Table 1080-1; only the table itself carries the note. The body ties on "1080-1".
    chunks = [
        _chunk("Section 1080 waterborne paint: see Table 1080-1 for the pigment composition."),
        _chunk(f"Table 1080-1\n{TABLE}\n{NOTES}", notes=True),
    ]
    index = IndexFile("m", chunks, np.zeros((2, 4), dtype=np.float32)).with_keyword_index()

    hits = index.keyword_search("footnote to Table 1080-1", k=2, division="wztc", field_boost=1.5,
                                ids=["Table 1080-1"], id_boost=2.0)

    assert hits[0].chunk is chunks[1]
