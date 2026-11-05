"""Division-scoped retrieval: vector and keyword search within one division, fused, then reranked.

The division filter is applied inside both searches (IndexFile.search and
IndexFile.keyword_search), so the reranker and the answer only ever see the
asked division's chunks.
"""

import re
from typing import Any, Dict, List, Optional, Sequence

from .embedder import Embedder, Reranker
from .index_file import Hit, IndexFile, search_text
from .keyword import fuse
from .timing import StepTimer, timed

# Vector hits handed to the reranker. 20 was enough for the 4 original manuals,
# but with about 20 documents per division (DAR-621) the right chunk can rank just
# below it: the UAM's lane-closure rule (p.126, 3.6.4.1) came 22nd for "At what
# distance from a travel lane does utility work require a lane closure?", so
# Utilities refused a question its manual answers. Of the 83 known-page
# questions, 69 find their page in the top 5 with 20 candidates, 72 with 25, 30
# or 35, and 75 with 40 (docs/stress-test-50-documents.md). The cost is on Vercel's
# 2 CPUs: reranking took 5.4 s for 40 against 3.0 s for 20 (0.45 s and 0.26 s locally).
DEFAULT_CANDIDATES = 40

# A Markdown pipe table: a row of cells, then the separator row (|---|---|) the
# PDF reader writes under the header. Chunks the index build tags kind="table"
# count too; this catches those of an index built before the tag existed.
_PIPE_TABLE = re.compile(r"^\s*\|.*\|\s*$\n^\s*\|?\s*:?-{3,}", re.MULTILINE)


def is_table(chunk: Dict[str, Any]) -> bool:
    """Whether the chunk is a table (tagged kind="table", or holding a Markdown pipe table)."""
    return chunk.get("kind") == "table" or bool(_PIPE_TABLE.search(chunk.get("text") or ""))


class Retriever:
    def __init__(self, index: IndexFile, embedder: Embedder, reranker: Optional[Reranker] = None,
                 candidates: int = DEFAULT_CANDIDATES, keyword: bool = True, text_only: bool = False):
        """`keyword` adds the keyword (BM25) search, when the index has one.

        `text_only` (RERANK_TEXT_ONLY) reranks only the text chunks and leaves
        tables at their fused rank (see `rerank_text_only`).
        """
        self.index = index
        self.embedder = embedder
        self.reranker = reranker
        self.candidates = candidates
        self.keyword = keyword and index.keyword is not None
        self.text_only = text_only

    def retrieve(self, question: str, division: Optional[str], k: int = 5,
                 timer: Optional[StepTimer] = None, candidates: Optional[int] = None,
                 sources: Optional[Sequence[str]] = None) -> List[Hit]:
        """The k best chunks of `division` for the question (all divisions when None).

        `sources` (document file names) limits the search to those documents.
        With a reranker, the top `candidates` hits (default: the retriever's)
        are re-ordered by the cross-encoder and their scores are the
        cross-encoder's. With keyword search, those candidates are the top of
        the vector and keyword rankings fused (reciprocal rank fusion), each
        search giving `candidates` hits. `timer` records the embed, search
        (both searches) and rerank steps.
        """
        pool = max(k, candidates or self.candidates) if self.reranker else k
        hits = self.candidates_for(question, division, pool, timer=timer, sources=sources)
        if self.reranker and len(hits) > 1:
            with timed(timer, "rerank"):
                hits = rerank_text_only(self.reranker, question, hits) if self.text_only else rerank(self.reranker, question, hits)
        return hits[:k]

    def candidates_for(self, question: str, division: Optional[str], pool: int,
                       timer: Optional[StepTimer] = None, sources: Optional[Sequence[str]] = None) -> List[Hit]:
        """The `pool` best chunks before any rerank: the vector hits, fused with the keyword hits when on.

        evaluation/rerank_ab.py reranks this same pool once per reranker.
        """
        with timed(timer, "embed"):
            vector = self.embedder.query(question)
        with timed(timer, "search"):
            hits = self.index.search(vector, k=pool, division=division, sources=sources)
            if self.keyword:
                words = self.index.keyword_search(question, k=pool, division=division, sources=sources)
                hits = _fused(hits, words)[:pool]
        return hits

    def warm_up(self) -> None:
        """Load the models and run each once on a few words.

        The first inference of an ONNX model is slow, so a cold instance runs one
        before the first question. Short text is enough: reranking 20 real
        passages here took about 4.6 s of a cold start on Vercel's CPU. Two
        full-length passages (the index's longest) added 0.5 s to the warm-up on
        Vercel and changed nothing after it. With all 20 passages in one batch,
        the first two questions still reranked about 0.6 s slower than later
        ones either way; one passage per call (embedder.RERANK_BATCH_SIZE) left
        the first questions 0.06 s slower than the same questions asked again,
        after either warm-up.
        """
        self.embedder.query("warm up")
        if self.reranker:
            self.reranker.scores("warm up", ["warm up"])

    def with_following(self, hits: List[Hit], top: int = 2) -> List[Hit]:
        """The hits, each of the first `top` followed by the next chunk of its document.

        A rule that runs onto the next page is split across two chunks; the
        second half often doesn't match the question on its own (the TMP manual's
        drop-off rule D continues on the next page as "3. Provide a lateral distance...").
        A following chunk comes from the same document, so the same division.
        """
        seen = {id(h.chunk) for h in hits}
        out: List[Hit] = []
        for rank, hit in enumerate(hits):
            out.append(hit)
            after = self.index.following(hit.chunk) if rank < top else None
            if after is not None and id(after) not in seen:
                seen.add(id(after))
                out.append(Hit(hit.score, after))
        return out

    def as_passages(self, hits: List[Hit]) -> List[Hit]:
        """The hits in reading order, with chunks that follow each other merged into one passage.

        A rule split across pages then reaches the model as one passage. With
        the halves as separate passages, the model mixed up the TMP manual's
        drop-off rules C and D (rule D's last item starts the next page). A
        merged passage keeps its first page as `page`, its last as `page_end`
        and the chunks it was made from as `parts` (answer.narrow uses them to
        cite only the pages an answer drew on).
        """
        passages: List[Hit] = []
        last_position = None
        for hit in sorted(hits, key=lambda h: self.index.position(h.chunk)):
            position = self.index.position(hit.chunk)
            previous = passages[-1].chunk if passages else None
            if previous is not None and position == last_position + 1 and previous.get("source") == hit.chunk.get("source"):
                merged = dict(previous, text=previous["text"] + "\n\n" + hit.chunk["text"])
                merged["parts"] = previous.get("parts", [previous]) + [hit.chunk]
                if hit.chunk.get("page") != previous.get("page"):
                    merged["page_end"] = hit.chunk.get("page")
                merged["section"] = _join_sections(previous.get("section"), hit.chunk.get("section"))
                passages[-1] = Hit(max(passages[-1].score, hit.score), merged)
            else:
                passages.append(hit)
            last_position = position
        return passages


def rerank(reranker: Reranker, question: str, hits: List[Hit]) -> List[Hit]:
    """The hits re-ordered by the cross-encoder, their scores now the cross-encoder's."""
    scores = reranker.scores(question, [search_text(h.chunk) for h in hits])
    return [Hit(s, h.chunk) for s, h in sorted(zip(scores, hits), key=lambda pair: -pair[0])]


def rerank_text_only(reranker: Reranker, question: str, hits: List[Hit]) -> List[Hit]:
    """Rerank the text chunks only; a table keeps the position the fused search gave it.

    The T2-RAGBench figure that motivated RERANK_TEXT_ONLY (.handoff/redo-nov4/B-retrieval.md):
    MiniLM-L6, trained on web passages, ranked text+table data worse than no reranker.
    Merge rule: the table hits stay at their fused positions; the text hits, sorted by
    cross-encoder score, fill the other positions top down. So a table that was fused
    3rd stays 3rd, and the best text chunk takes the first position that isn't a
    table's. A table's score becomes that of the reranked text hit just above it (the
    one just below when it is first), so the scores still read as cross-encoder scores
    (the refusal retry and the division suggestion compare them with thresholds).
    A pool of tables only keeps its fused order but takes the cross-encoder's scores,
    since fused scores (cosine or BM25) aren't on the thresholds' scale.
    """
    tables = [is_table(h.chunk) for h in hits]
    text_hits = [h for h, table in zip(hits, tables) if not table]
    if not text_hits:
        scores = reranker.scores(question, [search_text(h.chunk) for h in hits])
        return [Hit(s, h.chunk) for s, h in zip(scores, hits)]
    reranked = iter(rerank(reranker, question, text_hits))
    merged = [h if table else next(reranked) for h, table in zip(hits, tables)]
    first_text = next(h.score for h, table in zip(merged, tables) if not table)
    out: List[Hit] = []
    last_text_score = None
    for hit, table in zip(merged, tables):
        if table:
            hit = Hit(first_text if last_text_score is None else last_text_score, hit.chunk)
        else:
            last_text_score = hit.score
        out.append(hit)
    return out


def _fused(vector_hits: List[Hit], keyword_hits: List[Hit]) -> List[Hit]:
    """Both searches' hits, best first by reciprocal rank fusion; a chunk keeps its vector hit when it has one."""
    by_id = {id(h.chunk): h for h in keyword_hits}
    by_id.update({id(h.chunk): h for h in vector_hits})
    order = fuse([[id(h.chunk) for h in vector_hits], [id(h.chunk) for h in keyword_hits]])
    return [by_id[i] for i in order]


def _join_sections(first, second):
    names = [s for part in (first, second) if part for s in part.split("; ")]
    return "; ".join(dict.fromkeys(names)) or None
