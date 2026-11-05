"""Division-scoped retrieval: vector and keyword search within one division, fused, then reranked.

The division filter is applied inside both searches (IndexFile.search and
IndexFile.keyword_search), so the reranker and the answer only ever see the
asked division's chunks.
"""

from typing import Dict, List, Optional, Sequence, Tuple

from .embedder import Embedder, Reranker
from .index_file import Hit, IndexFile, is_figure, search_text
from .keyword import DEFAULT_FIELD_BOOST, DEFAULT_ID_BOOST, RRF_K, fuse
from .query import parse
from .timing import StepTimer, timed

# Page aggregation (DAR-657) is off until the locked question set picks between
# max and sum (DAR-652's final phase): on the dev sets both lowered hit@5
# (docs/page-aggregation.md).
PAGE_AGGREGATION_MODES = ("off", "max", "sum")
DEFAULT_PAGE_AGGREGATION = "off"
# A page gives at most this many chunks to the top k: a long table page split
# into three chunks would otherwise fill the whole context under `sum`.
DEFAULT_MAX_CHUNKS_PER_PAGE = 2
# 0 = no cap. A cap keeps a generic question ("what is a work zone?") from
# filling the top k with one manual's five pages while the other manuals' pages wait.
DEFAULT_MAX_CHUNKS_PER_DOCUMENT = 0
# Per-list multipliers inside reciprocal rank fusion: (vector, keyword).
DEFAULT_FUSION_WEIGHTS = (1.0, 1.0)

# Vector hits handed to the reranker. 20 was enough for the 4 original manuals,
# but with about 20 documents per division (DAR-621) the right chunk can rank just
# below it: the UAM's lane-closure rule (p.126, 3.6.4.1) came 22nd for "At what
# distance from a travel lane does utility work require a lane closure?", so
# Utilities refused a question its manual answers. Of the 83 known-page
# questions, 69 find their page in the top 5 with 20 candidates, 72 with 25, 30
# or 35, and 75 with 40 (docs/stress-test-50-documents.md). The cost is on Vercel's
# 2 CPUs: reranking took 5.4 s for 40 against 3.0 s for 20 (0.45 s and 0.26 s locally).
DEFAULT_CANDIDATES = 40


class Retriever:
    def __init__(self, index: IndexFile, embedder: Embedder, reranker: Optional[Reranker] = None,
                 candidates: int = DEFAULT_CANDIDATES, keyword: bool = True,
                 field_boost: float = DEFAULT_FIELD_BOOST, id_boost: float = DEFAULT_ID_BOOST,
                 page_aggregation: str = DEFAULT_PAGE_AGGREGATION,
                 max_chunks_per_page: int = DEFAULT_MAX_CHUNKS_PER_PAGE,
                 max_chunks_per_document: int = DEFAULT_MAX_CHUNKS_PER_DOCUMENT,
                 rrf_k: int = RRF_K, fusion_weights: Tuple[float, float] = DEFAULT_FUSION_WEIGHTS):
        """`keyword` adds the keyword (BM25) search, when the index has one; `field_boost` 0 turns its caption/ID field off.

        `page_aggregation`, `max_chunks_per_page` and `max_chunks_per_document`
        are aggregate_pages' settings, applied to the reranked candidates before
        the top k. `rrf_k` and `fusion_weights` (vector, keyword) go to the
        reciprocal rank fusion of the two searches.
        """
        if page_aggregation not in PAGE_AGGREGATION_MODES:
            raise ValueError(f"page_aggregation must be one of {PAGE_AGGREGATION_MODES}, got {page_aggregation!r}")
        self.index = index
        self.embedder = embedder
        self.reranker = reranker
        self.candidates = candidates
        self.keyword = keyword and index.keyword is not None
        self.field_boost = field_boost if index.keyword is not None and index.keyword.field is not None else 0.0
        self.id_boost = id_boost
        # Only reranker scores are comparable across hits (see retrieve), so without a reranker the
        # pages are not aggregated; the document cap still applies, in the fused order.
        self.page_aggregation = page_aggregation if reranker is not None else "off"
        self.max_chunks_per_page = max_chunks_per_page
        self.max_chunks_per_document = max_chunks_per_document
        self.rrf_k = rrf_k
        self.fusion_weights = fusion_weights

    def retrieve(self, question: str, division: Optional[str], k: int = 5,
                 timer: Optional[StepTimer] = None, candidates: Optional[int] = None,
                 sources: Optional[Sequence[str]] = None) -> List[Hit]:
        """The k best chunks of `division` for the question (all divisions when None).

        `sources` (document file names) limits the search to those documents.
        With a reranker, the top `candidates` hits (default: the retriever's)
        are re-ordered by the cross-encoder and their scores are the
        cross-encoder's. With keyword search, those candidates are the top of
        the vector and keyword rankings fused (reciprocal rank fusion), each
        search giving `candidates` hits. The keyword search scores the
        caption/ID field too, counting the table, figure and document numbers
        the question names (query.parse) more; the vector search gets the
        question as asked. `timer` records the embed, search (both searches)
        and rerank steps.
        """
        pool = max(k, candidates or self.candidates) if self.reranker else k
        with timed(timer, "embed"):
            vector = self.embedder.query(question)
        with timed(timer, "search"):
            hits = self.index.search(vector, k=pool, division=division, sources=sources)
            if self.keyword:
                parsed = parse(question)
                words = self.index.keyword_search(question, k=pool, division=division, sources=sources,
                                                  field_boost=self.field_boost, ids=parsed.ids + parsed.doc_codes,
                                                  id_boost=self.id_boost)
                hits = _fused(hits, words, k=self.rrf_k, weights=self.fusion_weights)[:pool]
        if self.reranker and len(hits) > 1:
            with timed(timer, "rerank"):
                scores = self.reranker.scores(question, [search_text(h.chunk) for h in hits])
            hits = [Hit(s, h.chunk) for s, h in sorted(zip(scores, hits), key=lambda pair: -pair[0])]
        # Pages are only aggregated after a rerank (__init__ turns it off without a reranker): unreranked,
        # a chunk only the keyword search found carries its BM25 score (8.4) and the others their cosine
        # (under 1), so ranking pages by score would throw away the fusion's order.
        return aggregate_pages(hits, self.page_aggregation, k, max_per_page=self.max_chunks_per_page,
                               max_per_document=self.max_chunks_per_document)

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

        With page aggregation on, `top` counts pages, not chunks: the first two
        hits are often the two halves of one page, and the second page would
        otherwise lose its continuation. Every chunk of those pages may lead,
        but at most `top` following chunks are added, as without aggregation,
        so the prompt doesn't grow (one half's next chunk is usually the other
        half, already in the hits).

        A rule that runs onto the next page is split across two chunks; the
        second half often doesn't match the question on its own (the TMP manual's
        drop-off rule D continues on the next page as "3. Provide a lateral distance...").
        A following chunk comes from the same document, so the same division.
        """
        seen = {id(h.chunk) for h in hits}
        if self.page_aggregation == "off":
            lead = {id(h.chunk) for h in hits[:top]}
        else:
            pages = list(dict.fromkeys(_page_key(h.chunk) for h in hits))[:top]
            lead = {id(h.chunk) for h in hits if _page_key(h.chunk) in pages}
        out: List[Hit] = []
        added = 0
        for hit in hits:
            out.append(hit)
            after = self.index.following(hit.chunk) if id(hit.chunk) in lead and added < top else None
            if after is not None and id(after) not in seen:
                seen.add(id(after))
                added += 1
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
            if (previous is not None and position == last_position + 1 and previous.get("source") == hit.chunk.get("source")
                    and not is_figure(previous) and not is_figure(hit.chunk)):
                merged = dict(previous, text=previous["text"] + "\n\n" + hit.chunk["text"])
                merged["parts"] = previous.get("parts", [previous]) + [hit.chunk]
                # A part may span pages itself (a table joined over a page break at
                # build time carries its own page_end), so the passage ends at the last page of any part.
                last = max((p.get("page_end") or p.get("page") or 0 for p in merged["parts"]), default=0)
                merged.pop("page_end", None)
                if last and last != previous.get("page"):
                    merged["page_end"] = last
                merged["section"] = _join_sections(previous.get("section"), hit.chunk.get("section"))
                passages[-1] = Hit(max(passages[-1].score, hit.score), merged)
            else:
                passages.append(hit)
            last_position = position
        return passages


def aggregate_pages(hits: List[Hit], mode: str, k: int, max_per_page: int = DEFAULT_MAX_CHUNKS_PER_PAGE,
                    max_per_document: int = DEFAULT_MAX_CHUNKS_PER_DOCUMENT) -> List[Hit]:
    """The top k of the reranked hits, chosen page by page instead of chunk by chunk.

    A table split in two chunks loses to two weak text chunks from other pages
    when chunks are ranked one by one: each half scores a little below them, so
    neither reaches the top 5 although the page is the best answer. Here each
    hit is first grouped under its page, the key (source, page, page_end): a
    chunk that spans pages (page_end set) is its own group, not the first page's.

    The page's score is, over its chunks' reranker scores (Retriever only
    aggregates after a rerank):

        max   the best chunk's score
        sum   the best chunk's score + 0.5 x the sum of the other chunks'
              scores above zero (a second strong chunk lifts the page; a weak
              one leaves it where its best chunk put it, as the cross-encoder
              gives most of the 40 candidates a negative logit and the page
              would otherwise score below a lone chunk)
        off   no aggregation: the hits as they came, cut to k (only
              `max_per_document` applies, each chunk counted on its own)

    Pages are ordered by that score (ties keep the first page seen, i.e. the
    one with the better chunk rank), and their chunks, best first, are taken
    in that order until k are collected. One page gives at most
    `max_per_page` chunks and one document (source) at most `max_per_document`
    when that is above 0, so both halves of the table page make it, but a long
    page or a single manual cannot fill the whole top k. The caps give way
    when nothing else is left: chunks they held back fill the rest of the top
    k, best first (a visitor who picked one document still gets k passages).
    Scores are kept as
    they were (the reranker's), so retry and suggestion thresholds still read
    them.
    """
    if mode not in PAGE_AGGREGATION_MODES:
        raise ValueError(f"mode must be one of {PAGE_AGGREGATION_MODES}, got {mode!r}")
    if mode == "off" and max_per_document <= 0:
        return hits[:k]
    if mode == "off":
        groups = [[hit] for hit in hits]  # every chunk on its own, in the order it came: only the document cap applies
    else:
        pages: Dict[Tuple, List[Hit]] = {}
        for hit in sorted(hits, key=lambda h: -h.score):
            pages.setdefault(_page_key(hit.chunk), []).append(hit)
        if mode == "max":
            score = lambda group: group[0].score  # noqa: E731
        else:
            score = lambda group: group[0].score + 0.5 * sum(max(h.score, 0.0) for h in group[1:])  # noqa: E731
        groups = sorted(pages.values(), key=lambda g: -score(g))
    out: List[Hit] = []
    held: List[Hit] = []
    per_document: Dict[Optional[str], int] = {}
    for group in groups:
        source = group[0].chunk.get("source")
        for n, hit in enumerate(group):
            if n >= max_per_page or (max_per_document > 0 and per_document.get(source, 0) >= max_per_document):
                held.append(hit)
                continue
            out.append(hit)
            per_document[source] = per_document.get(source, 0) + 1
    out = out[:k]
    return out + sorted(held, key=lambda h: -h.score)[:k - len(out)]


def _page_key(chunk) -> Tuple:
    return (chunk.get("source"), chunk.get("page"), chunk.get("page_end"))


def _fused(vector_hits: List[Hit], keyword_hits: List[Hit], k: int = RRF_K,
           weights: Optional[Sequence[float]] = None) -> List[Hit]:
    """Both searches' hits, best first by reciprocal rank fusion; a chunk keeps its vector hit when it has one.

    `k` and `weights` (vector, keyword) are keyword.fuse's.
    """
    by_id = {id(h.chunk): h for h in keyword_hits}
    by_id.update({id(h.chunk): h for h in vector_hits})
    order = fuse([[id(h.chunk) for h in vector_hits], [id(h.chunk) for h in keyword_hits]], k=k, weights=weights)
    return [by_id[i] for i in order]


def _join_sections(first, second):
    names = [s for part in (first, second) if part for s in part.split("; ")]
    return "; ".join(dict.fromkeys(names)) or None
