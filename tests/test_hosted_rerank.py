"""Tests for the reranker settings, the text-only rerank and the A/B harness (DAR-657, no model download)."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

HOSTED = Path(__file__).resolve().parent.parent / "hosted"
sys.path.insert(0, str(HOSTED))

from divrag.config import load_settings  # noqa: E402
from divrag.embedder import RERANK_MODEL_FILE, RERANK_MODEL_NAME, Reranker, reranker_from_settings  # noqa: E402
from divrag.index_file import Hit, IndexFile  # noqa: E402
from divrag.retrieval import Retriever, is_table, rerank_text_only  # noqa: E402

_spec = importlib.util.spec_from_file_location("fetch_models", HOSTED / "scripts" / "fetch_models.py")
fetch_models = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_models)

TABLE = "| Offset | 40 mph |\n|---|---|\n| 14 ft | 27.42 |"


class _ByLength:
    """A reranker double: longer passages score higher."""

    def __init__(self):
        self.seen = []

    def scores(self, question, passages):
        self.seen.append(list(passages))
        return [float(len(p)) for p in passages]


def _hit(text, score=0.0, **extra):
    return Hit(score, {"text": text, "source": "a.pdf", "page": 1, "section": None, "division": "a", **extra})


def test_default_reranker_is_unchanged():
    settings = load_settings({})
    assert settings.rerank and settings.rerank_model == RERANK_MODEL_NAME
    assert settings.rerank_model_file == RERANK_MODEL_FILE == "onnx/model_quantized.onnx"
    assert settings.rerank_text_only and settings.rerank_batch_size == 1
    reranker = reranker_from_settings(settings)
    assert (reranker.model_name, reranker.model_file, reranker.batch_size) == (RERANK_MODEL_NAME, RERANK_MODEL_FILE, 1)


@pytest.mark.parametrize("value", ["none", "None", " NONE "])
def test_rerank_model_none_turns_the_reranker_off(value):
    settings = load_settings({"RERANK_MODEL": value})
    assert settings.rerank is False and reranker_from_settings(settings) is None


def test_another_fastembed_reranker_reads_its_own_file_and_a_typo_stops_startup():
    settings = load_settings({"RERANK_MODEL": "jinaai/jina-reranker-v1-turbo-en", "RERANK_TEXT_ONLY": "on",
                              "RERANK_BATCH_SIZE": "8"})
    assert settings.rerank_model_file is None and settings.rerank_text_only and settings.rerank_batch_size == 8
    assert Reranker(settings.rerank_model).model_file is None
    with pytest.raises(ValueError, match="RERANK_MODEL"):
        load_settings({"RERANK_MODEL": "Xenova/ms-marco-MiniLM-L-6"})
    with pytest.raises(ValueError, match="RERANK_TEXT_ONLY"):
        load_settings({"RERANK_TEXT_ONLY": "maybe"})
    with pytest.raises(ValueError, match="RERANK_BATCH_SIZE"):
        load_settings({"RERANK_BATCH_SIZE": "0"})


def test_tables_are_found_by_tag_or_by_their_pipe_table():
    assert is_table(_hit("anything", kind="table").chunk)
    assert is_table(_hit("Figure 4\n" + TABLE).chunk)
    assert not is_table(_hit("A | in a sentence | is not a table").chunk)


def test_text_only_keeps_tables_at_their_fused_rank_and_reranks_the_text_around_them():
    hits = [_hit("short", 4), _hit(TABLE, 3), _hit("a much longer text chunk", 2), _hit("mid text", 1)]
    reranker = _ByLength()

    out = rerank_text_only(reranker, "q", hits)

    assert reranker.seen == [["short", "a much longer text chunk", "mid text"]]  # the table never reaches the model
    assert [h.chunk["text"] for h in out] == ["a much longer text chunk", TABLE, "mid text", "short"]
    # The table carries the score of the reranked text hit just above it, so thresholds still compare.
    assert out[1].score == out[0].score == float(len("a much longer text chunk"))


def test_text_only_with_a_table_first_takes_the_next_text_score_and_all_tables_stay_as_fused():
    hits = [_hit(TABLE, 9), _hit("ab", 1), _hit("abcd", 0)]
    out = rerank_text_only(_ByLength(), "q", hits)
    assert [h.chunk["text"] for h in out] == [TABLE, "abcd", "ab"] and out[0].score == 4.0
    tables = [_hit(TABLE + " ", 2), _hit(TABLE, 1)]
    out = rerank_text_only(_ByLength(), "q", tables)
    # Fused order kept, but cross-encoder scores, which the retry and suggestion thresholds expect.
    assert [h.chunk for h in out] == [h.chunk for h in tables]
    assert [h.score for h in out] == [float(len(TABLE) + 1), float(len(TABLE))]


def test_retriever_uses_text_only_when_set():
    chunks = [_hit(t).chunk for t in ("short", TABLE, "a longer text chunk")]
    vectors = np.zeros((3, 3), dtype=np.float32)
    vectors[:, 0] = [1.0, 0.9, 0.8]
    index = IndexFile("m", chunks, vectors)

    class _Embedder:
        def query(self, text):
            return np.array([1.0, 0, 0], dtype=np.float32)

    retriever = Retriever(index, _Embedder(), _ByLength(), keyword=False, text_only=True)
    assert [h.chunk["text"] for h in retriever.retrieve("q", "a", k=3)] == ["a longer text chunk", TABLE, "short"]
    assert [h.chunk["text"] for h in retriever.candidates_for("q", "a", 3)] == ["short", TABLE, "a longer text chunk"]


def test_fetch_models_knows_every_fastembed_cross_encoder_and_the_file_it_reads():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    from divrag.embedder import cross_encoder_name

    cross_encoder_name()  # registers the int8 MiniLM file as a custom model; not one fastembed ships
    listed = {m.model: (m.sources.hf, m.model_file) for m in TextCrossEncoder._list_supported_models()
              if m.model != cross_encoder_name()}
    assert listed == fetch_models.CROSS_ENCODERS


def test_models_to_fetch_defaults_to_the_pinned_pair_and_follows_rerank_model():
    assert fetch_models.models_to_fetch() == list(fetch_models.MODELS)
    assert fetch_models.models_to_fetch("none") == [fetch_models.MODELS[0]]
    jina = fetch_models.models_to_fetch("jinaai/jina-reranker-v1-turbo-en")[1]
    assert jina == {"repo": "jinaai/jina-reranker-v1-turbo-en", "revision": "main", "model_file": "onnx/model.onnx"}
    with pytest.raises(ValueError):
        fetch_models.models_to_fetch("nope/model")


def test_ab_harness_reads_only_the_tuning_split_and_ranks_gold_pages(tmp_path):
    from evaluation.rerank_ab import gold_rank, summarize, tuning_cases

    items = [
        {"id": "t1", "division": "a", "question": "q1", "split": "tuning", "refuse": False,
         "expected": {"source": "a.pdf", "pdf_pages": [5]}},
        {"id": "l1", "division": "a", "question": "q2", "split": "locked", "refuse": False,
         "expected": {"source": "a.pdf", "pdf_pages": [6]}},
        {"id": "t2", "division": "a", "question": "q3", "split": "tuning", "refuse": True, "expected": None},
    ]
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"division": "a", "items": items}), encoding="utf-8")
    cases = tuning_cases(path)
    assert [c["id"] for c in cases] == ["t1"]

    case = cases[0]
    top = [{"source": "b.pdf", "page": 5}, {"source": "a.pdf", "page": 4, "page_end": 6}]
    assert gold_rank(top, case) == 2  # a chunk spanning pages 4-6 covers page 5
    assert gold_rank(top[:1], case) is None
    stats = summarize([{"rank": 1, "seconds": 0.2}, {"rank": None, "seconds": 0.4}])
    assert stats == {"cases": 2, "hit1": 1, "hit5": 1, "mrr": 0.5, "seconds_per_question": 0.3}


def test_fetch_models_reads_none_as_config_does_and_fetches_external_onnx_data():
    assert fetch_models.models_to_fetch(" None ") == [fetch_models.MODELS[0]]
    model = {"repo": "r", "revision": "main", "model_file": "onnx/model.onnx"}
    siblings = [{"rfilename": n, "size": 1} for n in ("onnx/model.onnx", "onnx/model.onnx_data", "onnx/model_int8.onnx",
                                                       "config.json", "README.md")]
    assert set(fetch_models.files_to_fetch(model, siblings)) == {"onnx/model.onnx", "onnx/model.onnx_data", "config.json"}


def test_known_cross_encoders_leave_out_custom_files_registered_earlier():
    from divrag.embedder import cross_encoder_name, known_cross_encoders

    name = cross_encoder_name()  # registers the int8 MiniLM file as a custom model
    assert name not in known_cross_encoders() and RERANK_MODEL_NAME in known_cross_encoders()
