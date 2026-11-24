"""Tests for "All divisions" (DAR-666): the merged search and its settings, with a tiny index; no model download."""

import sys
from pathlib import Path

import numpy as np
import pytest

HOSTED = Path(__file__).resolve().parent.parent / "hosted"
sys.path.insert(0, str(HOSTED))

from divrag.answer import Answerer, build_messages, refusal_text  # noqa: E402
from divrag.config import load_settings  # noqa: E402
from divrag.divisions import ALL, BY_ID, DIVISIONS, is_all, target_for  # noqa: E402
from divrag.index_file import Hit, IndexFile  # noqa: E402
from divrag.retrieval import Retriever  # noqa: E402


class _Embedder:
    """Every query is the same unit vector, so the vector search ranks chunks by their first coordinate."""

    def query(self, text):
        return np.array([1.0, 0.0], dtype=np.float32)


class _Reranker:
    """Scores a passage by the number in its text, and records how many it was given."""

    def __init__(self):
        self.seen = []

    def scores(self, question, passages):
        self.seen.append(len(passages))
        return [float(p.split()[-1]) for p in passages]


def _index():
    """Three divisions with 5 chunks each; each chunk's vector score and rerank score are set by hand."""
    chunks, vectors = [], []
    for division, base in (("wztc", 0.9), ("utilities", 0.5), ("tmsd", 0.1)):
        for n in range(5):
            # The vector search prefers wztc's chunks; the reranker prefers each division's last ones.
            chunks.append({"text": f"{division} chunk {n} {n + (10 if division == 'tmsd' else 0)}",
                           "source": f"{division}.pdf", "page": n + 1, "division": division})
            score = base - n * 0.01
            vectors.append([score, float(np.sqrt(1 - score * score))])
    return IndexFile("test", chunks, np.array(vectors, dtype=np.float32))


def _retriever(candidates=3):
    return Retriever(_index(), _Embedder(), _Reranker(), candidates=candidates, keyword=False, text_only=False)


def test_each_division_gets_its_own_candidates_before_one_rerank():
    retriever = _retriever(candidates=3)

    hits = retriever.retrieve_across("q", ["wztc", "utilities", "tmsd"], k=4, merged=9)

    # The vector search alone would give wztc's chunks only; each division's top 3 were merged instead,
    # reranked once (9 passages), and the reranker put tmsd's chunks first.
    assert retriever.reranker.seen == [9]
    assert [h.chunk["division"] for h in hits] == ["tmsd", "tmsd", "tmsd", "wztc"]
    assert hits[0].score == 12.0


def test_the_merged_pool_interleaves_the_divisions_ranks():
    retriever = _retriever(candidates=3)

    retriever.retrieve_across("q", ["wztc", "utilities", "tmsd"], k=3, merged=3)

    # Only the merged pool's best 3 are reranked: rank 1 of each division.
    assert retriever.reranker.seen == [3]


def test_only_the_listed_divisions_and_ticked_documents_are_searched():
    retriever = _retriever(candidates=5)

    hits = retriever.retrieve_across("q", ["wztc", "utilities"], k=10, merged=20)
    assert {h.chunk["division"] for h in hits} == {"wztc", "utilities"}

    hits = retriever.retrieve_across("q", ["wztc", "utilities", "tmsd"], k=10, merged=20,
                                     sources=["utilities.pdf"])
    assert {h.chunk["source"] for h in hits} == {"utilities.pdf"}


def test_a_single_divisions_search_is_unchanged():
    retriever = _retriever(candidates=3)

    hits = retriever.retrieve("q", "wztc", k=2)

    assert retriever.reranker.seen == [3]
    assert [h.chunk["division"] for h in hits] == ["wztc", "wztc"]


def test_all_divisions_is_a_target_of_every_document_but_no_division_row():
    assert target_for("all") is ALL and is_all(ALL)
    assert target_for("utilities") is BY_ID["utilities"] and target_for("nope") is None
    assert "all" not in BY_ID and ALL not in DIVISIONS
    assert ALL.documents == tuple(doc for d in DIVISIONS for doc in d.documents)


def test_the_all_divisions_settings_default_and_are_checked():
    settings = load_settings({})
    assert (settings.all_divisions_top_k, settings.all_divisions_candidates) == (8, 40)
    assert load_settings({"ALL_DIVISIONS_TOP_K": "5", "ALL_DIVISIONS_CANDIDATES": "60"}).all_divisions_candidates == 60
    with pytest.raises(ValueError, match="ALL_DIVISIONS_TOP_K"):
        load_settings({"ALL_DIVISIONS_TOP_K": "0"})
    with pytest.raises(ValueError, match="ALL_DIVISIONS_CANDIDATES"):
        load_settings({"ALL_DIVISIONS_CANDIDATES": "121"})


def test_the_answerer_reads_more_passages_only_for_all_divisions():
    retriever = _retriever(candidates=5)
    answerer = Answerer(retriever, llm=None, top_k=2, all_top_k=4, merged_candidates=15)

    one = answerer.retrieve("q", BY_ID["wztc"])
    every = answerer.retrieve("q", ALL)

    assert answerer.top_k_for(BY_ID["wztc"]) == 2 and answerer.top_k_for(ALL) == 4
    assert {h.chunk["division"] for h in one} == {"wztc"}
    # The 4 best reranked chunks, all tmsd's here, merged into one passage as they follow each other.
    assert sum(len(h.chunk.get("parts", [h.chunk])) for h in every) == 4 and {h.chunk["division"] for h in every} == {"tmsd"}
    # The rest of the reranked pool is kept for the retry after a refusal, as for one division.
    assert len(every.more) == 15 - 4


def test_the_all_divisions_prompt_names_each_passages_division_and_the_refusal_suggests_none():
    hits = [Hit(1.0, {"text": "a", "source": "x.pdf", "page": 1, "division": "utilities"}),
            Hit(0.5, {"text": "b", "source": "y.pdf", "page": 2, "division": "tmsd"})]

    system, user = (m["content"] for m in build_messages("q?", BY_ID["wztc"], ALL, hits))

    assert "every division in this demo (Work Zone Traffic Control; Utilities;" in system
    assert "The person asking works in Work Zone Traffic Control" in system
    assert "[1] (Utilities · x.pdf, PDF page 1)" in user
    assert "[2] (Transportation Mobility and Safety · y.pdf, PDF page 2)" in user
    text = refusal_text(ALL, [])
    assert text.startswith(f"I couldn't find an answer to that in any division's documents ({len(ALL.documents)} documents")
    assert "try asking" not in text
