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


# DAR-657: identifiers kept whole, the caption/ID field and its boost.

from divrag.index_file import context_parts, field_text  # noqa: E402
from divrag.keyword import VERSION  # noqa: E402


def test_tokens_keep_table_ids_codes_fractions_and_fold_units():
    assert tokens("Table 6H-3 and Table 3-2") == ["table", "6h-3", "6h", "3", "table", "3-2", "3", "2"]
    assert tokens("Table 3-2", parts=False) == ["table", "3-2"]
    assert tokens("Form 04-20340, 1/2 mile") == ["form", "04-20340", "04", "20340", "1/2", "1", "2", "mile"]
    assert tokens("12' lane, 25.37\" deflection, 6 in. drop, 3 feet, 50% of 1,500") == [
        "12", "ft", "lane", "25.37", "in", "deflection", "6", "in", "drop", "3", "ft", "50", "pct", "1500"]
    assert tokens("right-of-way drop-off") == ["right", "way", "drop", "off"]  # no digit: just the words
    assert tokens("the lane edge in the work zone") == ["lane", "edge", "work", "zone"]  # bare "in" stays a stopword


def test_context_parts_reads_segments_by_shape_not_position():
    assert context_parts("[TMP Design Manual · p.38 · Figure 5 – NC-PCB table; Table 3 – Deflections]") == {
        "title": "TMP Design Manual", "captions": ["Figure 5 – NC-PCB table", "Table 3 – Deflections"]}
    # Another build may put a "printed p.13" segment after the page.
    assert context_parts("[TMP Design Manual · p.37 · printed p.13 · Table 3 – Deflections]")["captions"] == [
        "Table 3 – Deflections"]
    assert context_parts("[TMP Design Manual · p.2]") == {"title": "TMP Design Manual", "captions": []}


def test_field_text_holds_captions_ids_codes_and_section_but_not_prose():
    chunk = _chunk("**Table 4-1 Taper lengths**\nSee Figure 2-1 and Section 4.2 of form 04-20340.\n"
                   "Table 6 is referred to in this long sentence of prose that goes on well past any caption length "
                   "and should not be taken for a caption because captions are short labels, not paragraphs of text.",
                   5, context="[Work Zone Manual · p.5 · Figure 9 – Taper]", section="Chapter 4")
    lines = field_text(chunk).splitlines()
    assert lines[:2] == ["Figure 9 – Taper", "Table 4-1 Taper lengths"]
    assert {"Figure 2-1", "Section 4.2", "Table 6", "04-20340", "Chapter 4", "a"} <= set(lines)
    assert not any(line.startswith("Table 6 is referred") for line in lines)


def _id_index():
    # Page 10 is captioned "Table 3-2"; pages 11-13 are tables full of 3s and 2s, as most table pages are.
    chunks = [_chunk("| Speed | Width |\n| 40 | 11 |", 10, context="[Manual · p.10 · Table 3-2 – Lane widths]"),
              _chunk("| 3 | 2 | 3 | 2 | lane width 3 2 |", 11), _chunk("| 2 | 3 | 32 | 23 | 3 2 3 |", 12),
              _chunk("Table 3 lists 2 more widths; width 3, 2", 13),
              _chunk("guardrail flare rates", 14, division="b", context="[Other · p.14 · Table 3-2 – Flares]")]
    return IndexFile("m", chunks, np.zeros((len(chunks), 3), dtype=np.float32)).with_keyword_index()


def test_a_question_naming_table_3_2_ranks_the_captioned_chunk_first():
    index = _id_index()
    question = "What lane width does Table 3-2 give?"

    boosted = index.keyword_search(question, k=4, division="a", field_boost=2.0, ids=["Table 3-2"], id_boost=2.0)

    assert boosted[0].chunk["page"] == 10
    assert all(h.chunk["division"] == "a" for h in boosted)  # the field never brings in another division
    assert {h.chunk["page"] for h in boosted} >= {11, 13}  # a boost, not a filter: chunks without the ID still rank


def test_retriever_counts_the_ids_the_question_names():
    index = _id_index()
    question = "What lane width does Table 3-2 give?"

    hits = Retriever(index, _Embedder(), candidates=4).retrieve(question, "a", k=4)  # no reranker: fused order
    off = Retriever(index, _Embedder(), candidates=4, field_boost=0.0)

    assert hits[0].chunk["page"] == 10
    assert off.field_boost == 0.0


def test_a_version_1_keyword_file_still_loads_and_gets_its_field_built(tmp_path):
    index = _id_index()
    index.save(tmp_path)
    body = index.keyword.body
    np.savez_compressed(tmp_path / KEYWORD_FILE, terms=body.terms, starts=body.starts, rows=body.rows,
                        weights=body.weights.astype(np.float16))  # DAR-651's file: no version, no field

    loaded = IndexFile.load(tmp_path)

    assert loaded.keyword.field is not None and loaded.keyword.version == VERSION  # rebuilt, body too
    hits = loaded.keyword_search("Table 3-2 lane width", k=4, division="a", field_boost=2.0, ids=["Table 3-2"])
    assert hits[0].chunk["page"] == 10
    loaded.keyword.save(tmp_path)
    with np.load(tmp_path / KEYWORD_FILE) as data:
        assert int(data["version"]) == VERSION and "field_terms" in data.files


def test_field_ids_are_spelled_as_the_question_parser_spells_them_and_captions_count_twice():
    chunk = _chunk("**Table 4-1 Taper lengths**\nsee Fig. 2-1 and tbl. 6h-3; slope 0.0200", 5)
    lines = field_text(chunk).splitlines()
    assert {"Figure 2-1", "Table 6H-3"} <= set(lines)
    assert lines.count("Table 4-1") == 2  # the caption's own ID, once from the text and once more as a caption
    assert "0200" not in lines  # a decimal is not a document code


def test_the_captioned_page_beats_a_page_that_only_cites_the_table():
    # Same document and section, as in the real index, where every field holds the title and section.
    section = "Chapter 3 Lane widths and shoulders"
    chunks = [_chunk("| 40 | 11 | 12 |", 10, context="[Roadway Design Manual · p.10 · Table 3-2 – Lane widths]",
                     section=section),
              _chunk("For lane widths see Table 3-2.", 11, context="[Roadway Design Manual · p.11]", section=section)]
    chunks += [_chunk(f"shoulder text {i}", 20 + i, context="[Roadway Design Manual · p.20]", section=section)
               for i in range(6)]
    index = IndexFile("m", chunks, np.zeros((len(chunks), 3), dtype=np.float32)).with_keyword_index()

    hits = index.keyword_search("Table 3-2", k=2, division="a", field_boost=2.0, ids=["Table 3-2"], id_boost=2.0)

    assert [h.chunk["page"] for h in hits] == [10, 11]


def test_the_id_boost_counts_the_number_not_the_label_word():
    index = _id_index()
    plain = index.keyword.scores("Table 3-2", field_boost=2.0)
    boosted = index.keyword.scores("Table 3-2", field_boost=2.0, ids=["Table 3-2"], id_boost=2.0)
    assert boosted[0] > plain[0]  # page 10 has "3-2" in its field
    assert boosted[3] == plain[3]  # page 13's field has "Table 3" but no "3-2": the label is not boosted
