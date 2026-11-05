"""Tests for page-level aggregation after reranking and the fusion/BM25 settings (DAR-657)."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.config import load_settings, retrieval_options  # noqa: E402
from divrag.index_file import Hit, IndexFile  # noqa: E402
from divrag.keyword import KeywordIndex, fuse  # noqa: E402
from divrag.retrieval import Retriever, aggregate_pages  # noqa: E402


def _hit(score, page, source="tmp.pdf", **extra):
    return Hit(score, {"text": f"{source} p{page} {score}", "source": source, "page": page, "section": None,
                       "division": "wztc", **extra})


# A table split in two chunks on page 38 (3.0 and 2.8), out-voted chunk by chunk
# by lone text chunks from pages 12 and 40 (3.2 and 2.9).
TABLE_HALF_A, TABLE_HALF_B = _hit(3.0, 38), _hit(2.8, 38)
LONE_STRONG, LONE_WEAKER, LONE_WEAKEST = _hit(3.2, 12), _hit(2.9, 40), _hit(1.0, 50)
RERANKED = [LONE_STRONG, TABLE_HALF_A, LONE_WEAKER, TABLE_HALF_B, LONE_WEAKEST]


def _pages(hits):
    return [h.chunk["page"] for h in hits]


def test_off_returns_the_hits_as_they_came_cut_to_k():
    assert aggregate_pages(RERANKED, "off", 3) == RERANKED[:3]
    assert aggregate_pages(RERANKED, "off", 10) == RERANKED
    assert aggregate_pages([], "off", 5) == []


def test_sum_lets_a_page_with_two_chunks_beat_a_stronger_lone_chunk_but_max_does_not():
    # sum: page 38 scores 3.0 + 0.5 * 2.8 = 4.4 > 3.2, so both halves come first.
    assert _pages(aggregate_pages(RERANKED, "sum", 3)) == [38, 38, 12]
    # max: pages keep their best chunk's score, so page 12 stays first; page 38 still comes in whole.
    assert _pages(aggregate_pages(RERANKED, "max", 3)) == [12, 38, 38]


def test_max_still_keeps_both_chunks_of_a_page_together():
    # Page 38's second half (2.8, rank 4) comes right after its first half, before page 40's lone chunk (2.9).
    assert _pages(aggregate_pages(RERANKED, "max", 4)) == [12, 38, 38, 40]


def test_a_weak_sibling_does_not_pull_its_page_below_its_best_chunk_under_sum():
    # The cross-encoder gives most candidates a negative logit; a -9 half must not sink page 38 (3.0 - 4.5 = -1.5)
    # below pages 40 and 50. The half still comes along with its page, as the second half of a split table would.
    hits = [_hit(3.0, 38), _hit(2.9, 40), _hit(-9.0, 38), _hit(2.0, 50)]
    assert _pages(aggregate_pages(hits, "sum", 3)) == [38, 38, 40]


def test_scores_are_kept_as_the_reranker_gave_them():
    out = aggregate_pages(RERANKED, "sum", 5)
    assert [h.score for h in out] == [3.0, 2.8, 3.2, 2.9, 1.0]
    assert out[0] is TABLE_HALF_A  # the same Hit objects, so id(chunk) bookkeeping downstream still works


def test_one_page_gives_at_most_max_per_page_chunks():
    hits = [_hit(3.0, 38), _hit(2.9, 38), _hit(2.8, 38), _hit(2.0, 40)]
    assert _pages(aggregate_pages(hits, "sum", 3)) == [38, 38, 40]
    # Capped at 1 there is nothing else left for the third place, so page 38's held-back second chunk fills it.
    assert _pages(aggregate_pages(hits, "sum", 3, max_per_page=1)) == [38, 40, 38]
    assert _pages(aggregate_pages(hits, "sum", 3, max_per_page=3)) == [38, 38, 38]


def test_one_document_gives_at_most_max_per_document_chunks_when_capped():
    hits = [_hit(3.0, 1, "a.pdf"), _hit(2.9, 2, "a.pdf"), _hit(2.8, 3, "a.pdf"), _hit(1.0, 7, "b.pdf")]
    assert [(h.chunk["source"], h.chunk["page"]) for h in aggregate_pages(hits, "max", 3, max_per_document=2)] == [
        ("a.pdf", 1), ("a.pdf", 2), ("b.pdf", 7)]
    assert _pages(aggregate_pages(hits, "max", 3)) == [1, 2, 3]  # 0: no cap
    # A visitor who picked one document: the cap gives way rather than return fewer than k passages.
    assert _pages(aggregate_pages(hits[:3], "max", 3, max_per_document=2)) == [1, 2, 3]
    # The cap works without page aggregation too, so setting it alone is not silently ignored.
    assert [(h.chunk["source"], h.chunk["page"]) for h in aggregate_pages(hits, "off", 3, max_per_document=2)] == [
        ("a.pdf", 1), ("a.pdf", 2), ("b.pdf", 7)]


def test_without_a_reranker_the_fused_order_is_kept_even_with_aggregation_on():
    # Unreranked scores mix BM25 and cosine scales, so sorting by them would undo the fusion.
    index = _index(RERANKED)
    hits = Retriever(index, _Embedder(), None, candidates=10, page_aggregation="sum").retrieve("q", "wztc", k=3)
    plain = Retriever(index, _Embedder(), None, candidates=10).retrieve("q", "wztc", k=3)
    assert hits == plain


def test_with_following_counts_pages_when_aggregating():
    chunks = [{"text": t, "source": "a.pdf", "page": p, "section": None, "division": "a"}
              for t, p in [("a1", 1), ("a2", 1), ("b", 2), ("b next", 3), ("c", 4)]]
    index = IndexFile("m", chunks, np.ones((5, 3), dtype=np.float32))
    hits = [Hit(3.0, chunks[0]), Hit(2.9, chunks[1]), Hit(2.5, chunks[2])]
    texts = lambda r: [h.chunk["text"] for h in r.with_following(hits)]  # noqa: E731
    # Off: the first two hits are page 1's halves, so page 2 gets no continuation (today's behaviour).
    assert texts(Retriever(index, _Embedder())) == ["a1", "a2", "b"]
    # On: the top two pages are 1 and 2, so page 2's next chunk comes along.
    assert texts(Retriever(index, _Embedder(), _Reranker(), page_aggregation="sum")) == ["a1", "a2", "b", "b next"]


def test_a_chunk_spanning_pages_is_its_own_page_group():
    span = _hit(2.0, 38, page_end=39)
    hits = [_hit(2.5, 38), span, _hit(2.4, 12)]
    # Page 38 alone scores 2.5 under sum (the 38-39 chunk is another group), so page 12 comes before the span.
    assert aggregate_pages(hits, "sum", 3) == [hits[0], hits[2], span]
    # Two chunks of the same 38-39 span do add up.
    span_b = _hit(1.0, 38, page_end=39)
    assert _pages(aggregate_pages([hits[0], span, hits[2], span_b], "sum", 3)) == [38, 38, 38]


def test_an_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        aggregate_pages(RERANKED, "mean", 3)
    with pytest.raises(ValueError):
        Retriever(IndexFile("m", [], np.zeros((0, 3), dtype=np.float32)), None, page_aggregation="mean")


class _Embedder:
    def query(self, question):
        return np.array([1, 0, 0], dtype=np.float32)


class _Reranker:
    """Scores from the chunk's text (the hand-built hits above carry theirs)."""

    def scores(self, question, passages):
        return [float(p.split()[-1]) for p in passages]


def _index(hits):
    chunks = [h.chunk for h in hits]
    return IndexFile("m", chunks, np.array([[1, 0, 0]] * len(chunks), dtype=np.float32))


def test_the_retriever_aggregates_after_the_rerank_and_before_the_top_k():
    index = _index(RERANKED)
    by_chunk = Retriever(index, _Embedder(), _Reranker(), candidates=10).retrieve("q", "wztc", k=3)
    by_page = Retriever(index, _Embedder(), _Reranker(), candidates=10, page_aggregation="sum").retrieve("q", "wztc", k=3)

    assert _pages(by_chunk) == [12, 38, 40]  # today's ranking: the default is off
    assert _pages(by_page) == [38, 38, 12]


def test_fusion_weights_scale_each_rankings_contribution():
    assert fuse([[1, 2], [3]], k=60) == [1, 3, 2]  # unweighted: rank 1 in either list ties, the first list wins
    assert fuse([[1, 2], [3]], k=60, weights=(1.0, 2.0)) == [3, 1, 2]
    assert fuse([[1, 2], [3]], k=60, weights=(2.0,)) == [1, 2, 3]  # a missing weight is 1
    assert fuse([[1], [2]], k=1) == [1, 2]


def test_the_retriever_passes_rrf_k_and_fusion_weights_to_the_fusion():
    chunks = [{"text": f"filler {i}", "source": "a.pdf", "page": i, "section": None, "division": "a"} for i in range(1, 4)]
    chunks.append({"text": "deflection 25.37", "source": "a.pdf", "page": 9, "section": None, "division": "a"})
    vectors = np.array([[1, 0, 0]] * 3 + [[0, 1, 0]], dtype=np.float32)  # the keyword hit ranks last by vector
    index = IndexFile("m", chunks, vectors).with_keyword_index()

    def first_page(**kw):
        return Retriever(index, _Embedder(), None, **kw).retrieve("deflection 25.37", "a", k=1)[0].chunk["page"]

    assert first_page() == 1  # the vector ranking wins the tie for rank 1
    assert first_page(fusion_weights=(1.0, 1.5)) == 9
    assert first_page(fusion_weights=(0.0, 1.0)) == 9


def test_bm25_parameters_are_used_at_build_and_saved_with_the_index(tmp_path):
    texts = ["lane closure " * 20, "lane", "detour"]
    divisions = ["a"] * 3
    default = KeywordIndex.build(texts, divisions)
    no_length_norm = KeywordIndex.build(texts, divisions, k1=1.2, b=0.0)

    assert (default.k1, default.b) == (1.2, 0.75)
    # With b = 0 the long chunk is not penalised for its length, so "lane" scores it higher than with b = 0.75.
    assert no_length_norm.scores("lane")[0] > default.scores("lane")[0]

    index = IndexFile("m", [{"text": t, "source": "a.pdf", "page": i, "section": None, "division": "a"}
                            for i, t in enumerate(texts, 1)], np.ones((3, 2), dtype=np.float32))
    index.with_keyword_index(k1=0.9, b=0.5).save(tmp_path)
    loaded = IndexFile.load(tmp_path)
    assert (loaded.keyword.k1, loaded.keyword.b) == (0.9, 0.5)


def test_aggregation_and_fusion_settings_have_defaults_that_keep_todays_ranking():
    s = load_settings({})
    assert (s.page_aggregation, s.max_chunks_per_page, s.max_chunks_per_document) == ("off", 2, 0)
    assert (s.rrf_k, s.fusion_weights, s.bm25_k1, s.bm25_b) == (60, (1.0, 1.0), 1.2, 0.75)

    s = load_settings({"PAGE_AGGREGATION": "Sum", "MAX_CHUNKS_PER_PAGE": "3", "MAX_CHUNKS_PER_DOCUMENT": "4",
                       "RRF_K": "20", "FUSION_WEIGHTS": "1, 0.5", "BM25_K1": "0.9", "BM25_B": "0.4"})
    assert (s.page_aggregation, s.max_chunks_per_page, s.max_chunks_per_document) == ("sum", 3, 4)
    assert (s.rrf_k, s.fusion_weights, s.bm25_k1, s.bm25_b) == (20, (1.0, 0.5), 0.9, 0.4)


@pytest.mark.parametrize("env", [
    {"PAGE_AGGREGATION": "mean"},
    {"MAX_CHUNKS_PER_PAGE": "0"},
    {"MAX_CHUNKS_PER_DOCUMENT": "-1"},
    {"RRF_K": "0"},
    {"FUSION_WEIGHTS": "1"},
    {"FUSION_WEIGHTS": "1,2,3"},
    {"FUSION_WEIGHTS": "1,x"},
    {"FUSION_WEIGHTS": "-1,1"},
    {"FUSION_WEIGHTS": "0,0"},
    {"FUSION_WEIGHTS": "nan,1"},
    {"FUSION_WEIGHTS": "inf,1"},
    {"BM25_K1": "-0.1"},
    {"BM25_B": "1.5"},
])
def test_bad_aggregation_and_fusion_settings_stop_startup(env):
    with pytest.raises(ValueError):
        load_settings(env)


def test_blank_settings_fall_back_to_the_defaults():
    # A `BM25_K1=` line left in .env must not stop startup or a rebuild.
    s = load_settings({"PAGE_AGGREGATION": "", "MAX_CHUNKS_PER_PAGE": " ", "RRF_K": "", "BM25_K1": "", "BM25_B": ""})
    assert (s.page_aggregation, s.max_chunks_per_page, s.rrf_k, s.bm25_k1, s.bm25_b) == ("off", 2, 60, 1.2, 0.75)


def test_retrieval_options_ignore_unrelated_settings_and_match_the_apps():
    # The offline measurements read only these, so a paid model or a long budget in the shell can't stop them.
    env = {"PAGE_AGGREGATION": "max", "OPENROUTER_MODEL": "paid/model", "REQUEST_BUDGET_SECONDS": "90"}
    assert retrieval_options(env)["page_aggregation"] == "max"
    app = load_settings({"PAGE_AGGREGATION": "max", "RRF_K": "30"}).retriever_options()
    assert {k: app[k] for k in retrieval_options({})} == retrieval_options({"PAGE_AGGREGATION": "max", "RRF_K": "30"})
    assert (app["candidates"], app["keyword"]) == (40, True)


def test_with_following_adds_no_more_continuations_when_aggregating():
    # Two pages of two non-consecutive chunks each: four leads, but still only `top` (2) continuations.
    chunks = [{"text": t, "source": "a.pdf", "page": p, "section": None, "division": "a"}
              for t, p in [("a1", 1), ("a1 next", 1), ("a2", 1), ("a2 next", 1), ("b1", 2), ("b1 next", 2),
                           ("b2", 2), ("b2 next", 2)]]
    index = IndexFile("m", chunks, np.ones((8, 3), dtype=np.float32))
    hits = [Hit(3.0, chunks[0]), Hit(2.9, chunks[2]), Hit(2.5, chunks[4]), Hit(2.4, chunks[6])]
    out = Retriever(index, _Embedder(), _Reranker(), page_aggregation="sum").with_following(hits)
    assert len(out) == len(hits) + 2
