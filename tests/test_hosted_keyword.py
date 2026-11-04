"""Tests for the hosted keyword (BM25) search and its fusion with the vector search (DAR-651)."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.answer import passage_text  # noqa: E402
from divrag.index_file import IndexFile, search_text  # noqa: E402
from divrag.keyword import KEYWORD_FILE, KeywordIndex, fuse, tokens  # noqa: E402
from divrag.retrieval import Retriever  # noqa: E402


def _chunk(text, page, division="a", **extra):
    return {"text": text, "source": f"{division}.pdf", "page": page, "section": None, "division": division, **extra}


def _index(chunks):
    vectors = np.zeros((len(chunks), 3), dtype=np.float32)
    vectors[:, 0] = 1  # every chunk equally close to the query: the keyword search decides
    return IndexFile("m", chunks, vectors).with_keyword_index()


def test_tokens_keep_numbers_and_section_numbers_and_drop_plurals_and_stopwords():
    assert tokens("The lane closures at 42.89 in, section 3.6.4.1 (NC-PCB)") == [
        "lane", "closure", "42.89", "section", "3.6.4.1", "nc", "pcb"]
    assert tokens("glass bus") == ["glass", "bus"]


def test_a_rare_number_ranks_its_chunk_first():
    chunks = [_chunk("Maximum deflection 35.89 in at 60 mph", 37), _chunk("Maximum deflection 25.37 in at 60 mph", 38),
              _chunk("Impact angle 11.5 degrees", 39)]
    index = _index(chunks)

    hits = index.keyword_search("deflection 25.37", k=3, division="a")

    assert [h.chunk["page"] for h in hits][:2] == [38, 37]
    assert hits[0].score > hits[1].score > 0
    assert index.keyword_search("nothing matches", k=3, division="a") == []


def test_keyword_search_never_returns_another_divisions_chunks():
    chunks = [_chunk("utility pole relocation", 1, "a"), _chunk("utility pole relocation pole pole", 1, "b"),
              _chunk("guardrail", 2, "b")]
    index = _index(chunks)

    assert [h.chunk["division"] for h in index.keyword_search("utility pole", k=5, division="a")] == ["a"]
    assert [h.chunk["source"] for h in index.keyword_search("pole", k=5, division="b", sources=["b.pdf"])] == ["b.pdf"]
    assert index.keyword_search("pole", k=5, division="b", sources=["a.pdf"]) == []


def test_idf_is_per_division():
    # "barrier" is in every chunk of b, so it says nothing there, but it is rare in a.
    chunks = [_chunk("barrier offset", 1, "a"), _chunk("offset only", 2, "a"), _chunk("lane width", 3, "a"),
              _chunk("barrier", 1, "b"), _chunk("barrier wall", 2, "b")]
    index = _index(chunks)
    a = index.keyword.scores("barrier")[0]
    b = index.keyword.scores("barrier")[3]
    assert a > b > 0


def test_keyword_index_is_saved_and_loaded_with_the_index(tmp_path):
    index = _index([_chunk("lane closure distance", 1), _chunk("flagger station", 2)])
    index.save(tmp_path)

    loaded = IndexFile.load(tmp_path)

    assert (tmp_path / KEYWORD_FILE).is_file()
    assert [h.chunk["page"] for h in loaded.keyword_search("flagger", k=2, division="a")] == [2]
    IndexFile("m", loaded.chunks, loaded.vectors).save(tmp_path)  # rebuilt without one: the old file goes
    assert not (tmp_path / KEYWORD_FILE).exists()
    assert IndexFile.load(tmp_path).keyword is None


def test_keyword_file_for_other_chunks_is_rejected(tmp_path):
    KeywordIndex.build(["a b", "c d", "e f"], ["a", "a", "a"]).save(tmp_path)
    try:
        KeywordIndex.load(tmp_path, n_chunks=2)
    except ValueError as error:
        assert "chunk 2" in str(error)
    else:
        raise AssertionError("expected a ValueError")


def test_fuse_ranks_by_reciprocal_rank_and_keeps_the_first_rankings_order_on_ties():
    assert fuse([[1, 2, 3], [3, 4]]) == [3, 1, 2, 4]  # 3 is in both
    assert fuse([[1, 2], [2, 1]]) == [1, 2]


class _Embedder:
    def query(self, question):
        return np.array([1, 0, 0], dtype=np.float32)


class _Reranker:
    def __init__(self):
        self.seen = []

    def scores(self, question, passages):
        self.seen.extend(passages)
        return [1.0 if "25.37" in p else 0.0 for p in passages]


def test_retriever_adds_keyword_hits_the_vector_search_missed():
    chunks = [_chunk(f"filler text {i}", i) for i in range(1, 6)] + [_chunk("deflection 25.37", 6)]
    vectors = np.array([[1, 0, 0]] * 5 + [[0, 1, 0]], dtype=np.float32)  # the vector search ranks page 6 last
    index = IndexFile("m", chunks, vectors).with_keyword_index()

    with_keyword = Retriever(index, _Embedder(), _Reranker(), candidates=3).retrieve("deflection 25.37", "a", k=1)
    vector_only = Retriever(index, _Embedder(), _Reranker(), candidates=3, keyword=False).retrieve(
        "deflection 25.37", "a", k=1)

    assert with_keyword[0].chunk["page"] == 6
    assert vector_only[0].chunk["page"] != 6


def test_retriever_without_a_keyword_index_uses_the_vector_search_only():
    index = IndexFile("m", [_chunk("x", 1)], np.array([[1, 0, 0]], dtype=np.float32))
    assert Retriever(index, _Embedder()).keyword is False


def test_the_context_line_is_reranked_and_shown_to_the_model_but_not_part_of_the_text():
    context = "[TMP Design Manual · p.38 · Figure 5 – NC-PCB impact design table for CONCRETE pavement]"
    chunks = [_chunk("|20|Maximum Deflection|25.37|", 38, context=context), _chunk("|20|Maximum Deflection|35.89|", 37)]
    index = IndexFile("m", chunks, np.array([[1, 0, 0], [1, 0, 0]], dtype=np.float32))
    reranker = _Reranker()

    Retriever(index, _Embedder(), reranker, keyword=False).retrieve("concrete deflection", "a", k=2)

    assert search_text(chunks[0]) == context + "\n|20|Maximum Deflection|25.37|"
    assert reranker.seen[0].startswith(context) or reranker.seen[1].startswith(context)
    assert chunks[0]["text"] == "|20|Maximum Deflection|25.37|"
    merged = dict(chunks[0], parts=[chunks[0], dict(chunks[0], text="more rows")])
    assert passage_text(merged) == f"{context}\n|20|Maximum Deflection|25.37|\n\nmore rows"  # once per page
