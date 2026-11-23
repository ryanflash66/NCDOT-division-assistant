"""Tests for the document register (DAR-674): every document has a level, the index carries it, old editions are left out."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.config import load_settings  # noqa: E402
from divrag.divisions import DIVISIONS  # noqa: E402
from divrag.index_file import CHUNKS_FILE, IndexFile  # noqa: E402
from divrag.register import LEVELS, REGISTER, REGISTER_FILE, Register, tag  # noqa: E402

INDEX_DIR = Path(__file__).resolve().parent.parent / "hosted" / "index"
LEVEL_ROWS = {level: {"label": level.title(), "description": ""} for level in LEVELS}


def _register(**documents):
    rows = {file: dict({"issuer": "x", "level": "state", "binding": "guidance", "edition": None,
                        "superseded_by": None}, **row) for file, row in documents.items()}
    return Register.from_json({"levels": LEVEL_ROWS, "documents": rows})


def test_every_document_in_divisions_has_exactly_one_register_row():
    files = [d.file for division in DIVISIONS for d in division.documents]
    assert sorted(files) == sorted(REGISTER.entries)


def test_register_rows_use_known_levels_and_bindings():
    data = json.loads(REGISTER_FILE.read_text(encoding="utf-8"))
    assert list(data["levels"]) == list(LEVELS)
    assert {e.level for e in REGISTER.entries.values()} <= set(LEVELS)
    assert {e.binding for e in REGISTER.entries.values()} <= {"rule", "guidance"}
    assert REGISTER.entry("part6.pdf").level == "federal"
    assert REGISTER.label("federal") == "Federal"


def test_the_committed_index_carries_each_documents_level_and_edition():
    chunks = json.loads((INDEX_DIR / CHUNKS_FILE).read_text(encoding="utf-8"))["chunks"]
    wrong = [c["source"] for c in chunks
             if c.get("level") != REGISTER.entry(c["source"]).level
             or c.get("edition") != REGISTER.entry(c["source"]).edition]
    assert not wrong, f"run `python -m prototype.ingest --retag`: {sorted(set(wrong))[:5]}"


def test_tag_replaces_old_tags_and_leaves_out_an_edition_the_register_lacks():
    register = _register(**{"a.pdf": {"level": "federal", "edition": "2023"}, "b.pdf": {"level": "internal"}})
    chunks = [{"source": "a.pdf", "level": "state"}, {"source": "b.pdf", "edition": "old"}, {"source": "c.pdf"}]

    tag(chunks, register)

    assert chunks == [{"source": "a.pdf", "level": "federal", "edition": "2023"},
                      {"source": "b.pdf", "level": "internal"}, {"source": "c.pdf"}]


@pytest.mark.parametrize("row, message", [
    ({"level": "county"}, "level"),
    ({"binding": "law"}, "binding"),
    ({"superseded_by": "missing.pdf"}, "superseded"),
    ({"superseded_by": "a.pdf"}, "superseded"),
])
def test_a_bad_register_row_stops_the_load(row, message):
    with pytest.raises(ValueError, match=message):
        _register(**{"a.pdf": row})


def _index(register, *sources):
    chunks = [{"text": f"text {i}", "source": s, "page": 1, "division": "wztc"} for i, s in enumerate(sources)]
    vectors = np.eye(len(sources), dtype=np.float32)
    return IndexFile("m", chunks, vectors, register=register)


def test_a_superseded_edition_is_never_searched_while_the_newer_one_is_in_the_index():
    register = _register(**{"old.pdf": {"superseded_by": "new.pdf"}, "new.pdf": {}})
    index = _index(register, "old.pdf", "new.pdf")

    # The query matches the old edition's chunk exactly; it still can't be returned.
    hits = index.search([1.0, 0.0], k=5, division="wztc")

    assert [h.chunk["source"] for h in hits] == ["new.pdf"]
    assert index.count("wztc") == 1
    assert index.count("wztc", ["old.pdf"]) == 0


def test_a_superseded_edition_is_searched_when_its_newer_one_is_not_in_the_index():
    register = _register(**{"old.pdf": {"superseded_by": "new.pdf"}, "new.pdf": {}, "other.pdf": {}})
    index = _index(register, "old.pdf", "other.pdf")

    assert {h.chunk["source"] for h in index.search([1.0, 0.0], k=5)} == {"old.pdf", "other.pdf"}


def test_supersession_follows_a_chain_of_editions():
    register = _register(**{"a.pdf": {"superseded_by": "b.pdf"}, "b.pdf": {"superseded_by": "c.pdf"}, "c.pdf": {}})

    assert register.superseded(["a.pdf", "c.pdf"]) == {"a.pdf"}
    assert register.superseded(["a.pdf", "b.pdf", "c.pdf"]) == {"a.pdf", "b.pdf"}
    assert register.superseded(["a.pdf"]) == set()


def test_the_committed_index_has_no_superseded_document_today():
    sources = {c["source"] for c in json.loads((INDEX_DIR / CHUNKS_FILE).read_text(encoding="utf-8"))["chunks"]}
    assert REGISTER.superseded(sources) == set()


def test_conflict_settings_default_to_the_check_on_and_the_models_judgment():
    settings = load_settings({})
    assert settings.conflict_check is True
    assert settings.document_precedence == ()

    settings = load_settings({"CONFLICT_CHECK": "off", "DOCUMENT_PRECEDENCE": "Federal, state"})
    assert settings.conflict_check is False
    assert settings.document_precedence == ("federal", "state")


@pytest.mark.parametrize("value", ["federal,county", "federal,federal"])
def test_a_bad_document_precedence_stops_startup(value):
    with pytest.raises(ValueError, match="DOCUMENT_PRECEDENCE"):
        load_settings({"DOCUMENT_PRECEDENCE": value})
