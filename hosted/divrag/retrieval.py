"""Division-scoped retrieval: vector and keyword search within one division, fused, then reranked.

The division filter is applied inside both searches (IndexFile.search and
IndexFile.keyword_search), so the reranker and the answer only ever see the
asked division's chunks. An "All divisions" question (retrieve_across, DAR-666)
searches each division the same way and merges their rankings before one rerank.
"""

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
# An "All divisions" question (DAR-666) searches each division for DEFAULT_CANDIDATES, then
# reranks this many of the merged ranking once. Reciprocal rank fusion interleaves the divisions'
# ranks, so 40 is about each division's top 13. On the locked set's 41 answerable tuning items
# asked of all divisions, 40, 60 and 120 found the same gold pages (38 in the top 5, 39 in the
# top 8; 40 asked of their own division), while 120 doubled the local rerank time (0.29 s, 0.41 s,
# 0.81 s per question; reranking 40 takes 5.4 s on Vercel's CPU). So the rerank costs what a
# single division's does.
DEFAULT_MERGED_CANDIDATES = 40

# A Markdown pipe table: a row of cells, then the separator row (|---|---|) the
# PDF reader writes under the header. Chunks the index build tags kind="table"
# count too; this catches those of an index built before the tag existed.
_PIPE_TABLE = re.compile(r"^\s*\|.*\|\s*$\n^\s*\|?\s*:?-{3,}", re.MULTILINE)


def is_table(chunk: Dict[str, Any]) -> bool:
    """Whether the chunk is a table (tagged kind="table", or holding a Markdown pipe table)."""
    return chunk.get("kind") == "table" or bool(_PIPE_TABLE.search(chunk.get("text") or ""))


# What a page's text may end with after its last sentence (DAR-736): blank lines, the folio
# ("B-16", "**3-13**", "**Appendix A-10**", "Page 5 of 12", "iv") and footnotes, which the PDF
# reader writes as "> **3** Available at ...". They are skipped before asking whether the page ends
# in the middle of something.
_FOLIO = re.compile(r"^\W*(?:page\s+)?(?:appendix\s+)?(?:[A-Z]{1,2}\s*[-.]\s*)?\d{1,4}(?:\s*-\s*\d{1,4})?(?:\s+of\s+\d+)?\W*$"
                    r"|^\W*[ivxlc]{1,6}\W*$", re.IGNORECASE)
_FOOTNOTE = re.compile(r"^\s*>")
# A list item: a bullet, "1." / "1)" / "(1)", or "a." / "a)" / "(a)".
_LIST_ITEM = re.compile(r"^\s*(?:[-*•▪◦–]|\(?\d{1,2}[.)]|\(?[a-zA-Z][.)])\s+")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")
# A line that ends a page and says the list goes on: "... where applicable; and", "including:".
_LEADS_ON = re.compile(r"(?:[:;,]|\b(?:and|or))$", re.IGNORECASE)
# Running headers, footers and slide titles are short lines with no sentence end ("Part 2: Chapter 5
# | July 2019| Page 44", "WORK ZONE IMPACTS ASSESSMENT", "# Impacts on Transportation Projects"). Up to
# this many are skipped at a page's end and at the next page's start.
_FURNITURE_LINES = 3
_FURNITURE_CHARS = 80
# How many more chunks of its page a hit may bring to reach the page's end (DAR-736). The FHWA work
# zone guide's eight policy issues (held-out wztc-h033) start in one chunk of printed p.3-13, run
# through the page's second chunk and end on 3-14: the hit is one chunk short of the page's end.
SAME_PAGE_REACH = 1


# A table of contents line: "Development and Implementation Process ......... 3-10". A contents
# page running over is no list a question asks for, and bringing the next one only costs context.
_LEADER_DOTS = re.compile(r"(?:\.\s?){5,}|…{2,}")


def _is_item(line: str) -> bool:
    return bool(_LIST_ITEM.match(line) or _TABLE_ROW.match(line)) and not _LEADER_DOTS.search(line)


def _furniture(line: str) -> bool:
    """A blank line, folio, footnote, heading or other short line with no sentence end: not the page's content."""
    text = line.strip()
    if not text or _FOLIO.match(text) or _FOOTNOTE.match(line) or text.startswith("#"):
        return True
    plain = text.replace("**", "").replace("_", "").strip()
    # A short line in lower case is the end or start of a sentence cut by the break, not a header.
    return (len(plain) < _FURNITURE_CHARS and not plain[:1].islower() and not _is_item(text)
            and not _SENTENCE_END.search(plain) and not _LEADS_ON.search(plain))


def _last_line(text: str) -> str:
    lines = (text or "").splitlines()
    skipped = 0
    while lines and (not lines[-1].strip() or _FOLIO.match(lines[-1].strip()) or _FOOTNOTE.match(lines[-1])
                     or (skipped < _FURNITURE_LINES and _furniture(lines[-1]))):
        skipped += 0 if not lines[-1].strip() else 1
        lines.pop()
    return lines[-1].strip() if lines else ""


def _first_line(text: str) -> str:
    lines = (text or "").splitlines()
    skipped = 0
    while lines and (not lines[0].strip() or (skipped < _FURNITURE_LINES and _furniture(lines[0]))):
        skipped += 0 if not lines[0].strip() else 1
        lines.pop(0)
    return lines[0].strip() if lines else ""


def leads_on(text: str) -> bool:
    """Whether a page's text ends on a line that says more follows: "...; and", "including:", or a table row."""
    last = _last_line(text)
    return bool((_is_item(last) and _TABLE_ROW.match(last)) or _LEADS_ON.search(last.replace("**", "").rstrip()))


def runs_over(text: str, next_text: str) -> bool:
    """Whether a list, table or sentence at the end of `text` goes on at the start of `next_text` (the next page).

    Running headers, footers, folios, footnotes and repeated slide titles are
    skipped on both sides; then it does when:

    - the page ends on a list item, a table row or a line that leads on (":",
      ";", "and") and the next page starts with a list item or table row: the
      UAM's list of what plans must show (held-out utilities-h072) ends printed
      p.B-16 on "- the limits of right-of-way ...; and" and B-17 starts "- the
      portion of the work ..."; a Federal-aid course's slide of impacts
      (utilities-h074) ends on its third bullet and the next slide, under the
      same title, has the rest;
    Looking at the next page too keeps this off the 4 in 5 page ends that look
    unfinished on their own (a footer, a drawing's label, a table of contents).

    A plain sentence cut by the break (no sentence end, next page in lower case)
    does not count. On the 286 held-out locked questions it more than doubled
    what this adds (mean context +34% instead of +15%, 194 questions changed
    instead of 137) for 2 more gold pages reached (247 instead of 245 of 272).
    """
    last, first = _last_line(text), _first_line(next_text)
    if not last or not first:
        return False
    return bool((_is_item(last) or _LEADS_ON.search(last.replace("**", "").rstrip())) and _is_item(first))


class Retriever:
    def __init__(self, index: IndexFile, embedder: Embedder, reranker: Optional[Reranker] = None,
                 candidates: int = DEFAULT_CANDIDATES, keyword: bool = True,
                 field_boost: float = DEFAULT_FIELD_BOOST, id_boost: float = DEFAULT_ID_BOOST,
                 page_aggregation: str = DEFAULT_PAGE_AGGREGATION,
                 max_chunks_per_page: int = DEFAULT_MAX_CHUNKS_PER_PAGE,
                 max_chunks_per_document: int = DEFAULT_MAX_CHUNKS_PER_DOCUMENT,
                 rrf_k: int = RRF_K, fusion_weights: Tuple[float, float] = DEFAULT_FUSION_WEIGHTS,
                 text_only: bool = False):
        """`keyword` adds the keyword (BM25) search, when the index has one; `field_boost` 0 turns its caption/ID field off.

        `page_aggregation`, `max_chunks_per_page` and `max_chunks_per_document`
        are aggregate_pages' settings, applied to the reranked candidates before
        the top k. `rrf_k` and `fusion_weights` (vector, keyword) go to the
        reciprocal rank fusion of the two searches. `text_only` (RERANK_TEXT_ONLY)
        reranks only the text chunks and leaves tables at their fused rank (see
        `rerank_text_only`).
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
        search giving `candidates` hits. The keyword search scores the
        caption/ID field too, counting the table, figure and document numbers
        the question names (query.parse) more; the vector search gets the
        question as asked. `timer` records the embed, search (both searches)
        and rerank steps.
        """
        pool = max(k, candidates or self.candidates) if self.reranker else k
        hits = self.candidates_for(question, division, pool, timer=timer, sources=sources)
        if self.reranker and len(hits) > 1:
            with timed(timer, "rerank"):
                hits = rerank_text_only(self.reranker, question, hits) if self.text_only else rerank(self.reranker, question, hits)
        # Pages are only aggregated after a rerank (__init__ turns it off without a reranker): unreranked,
        # a chunk only the keyword search found carries its BM25 score (8.4) and the others their cosine
        # (under 1), so ranking pages by score would throw away the fusion's order.
        return aggregate_pages(hits, self.page_aggregation, k, max_per_page=self.max_chunks_per_page,
                               max_per_document=self.max_chunks_per_document)

    def candidates_for(self, question: str, division: Optional[str], pool: int,
                       timer: Optional[StepTimer] = None, sources: Optional[Sequence[str]] = None) -> List[Hit]:
        """The `pool` best chunks before any rerank: the vector hits, fused with the keyword hits when on.

        evaluation/rerank_ab.py reranks this same pool once per reranker.
        """
        with timed(timer, "embed"):
            vector = self.embedder.query(question)
        with timed(timer, "search"):
            return self._searched(question, vector, division, pool, sources)

    def _searched(self, question: str, vector, division: Optional[str], pool: int,
                  sources: Optional[Sequence[str]]) -> List[Hit]:
        """One division's vector hits, fused with its keyword hits when on: the `pool` best, best first."""
        hits = self.index.search(vector, k=pool, division=division, sources=sources)
        if self.keyword:
            parsed = parse(question)
            words = self.index.keyword_search(question, k=pool, division=division, sources=sources,
                                              field_boost=self.field_boost, ids=parsed.ids + parsed.doc_codes,
                                              id_boost=self.id_boost)
            hits = _fused(hits, words, k=self.rrf_k, weights=self.fusion_weights)[:pool]
        return hits

    def retrieve_across(self, question: str, divisions: Sequence[str], k: int = 5,
                        timer: Optional[StepTimer] = None, merged: int = DEFAULT_MERGED_CANDIDATES,
                        sources: Optional[Sequence[str]] = None) -> List[Hit]:
        """The k best chunks of all `divisions` together (DAR-666, "All divisions").

        Each division is searched on its own, exactly as a question asked of it
        alone (its `candidates` vector and keyword hits, fused), with the question
        embedded once. The divisions' rankings are then merged by reciprocal rank
        fusion, and the `merged` best of that go to the reranker once (all of
        them without a reranker, cut to k). A division's own ranking is what is
        merged, not its scores: the keyword scores of two divisions are not on
        one scale, the ranks are. The cross-encoder's scores are, so the reranked
        pool is ordered across divisions by them, and aggregate_pages takes the k.

        The division filter still runs inside every search: only the listed
        divisions' chunks (and only `sources`' documents, when given) can reach
        the reranker or the answer.
        """
        pool = self.candidates if self.reranker else k
        with timed(timer, "embed"):
            vector = self.embedder.query(question)
        with timed(timer, "search"):
            rankings = [self._searched(question, vector, division, pool, sources) for division in divisions]
            by_id = {id(h.chunk): h for ranking in rankings for h in ranking}
            order = fuse([[id(h.chunk) for h in ranking] for ranking in rankings], k=self.rrf_k)
            hits = [by_id[i] for i in order][:max(k, merged) if self.reranker else k]
        if self.reranker and len(hits) > 1:
            with timed(timer, "rerank"):
                hits = rerank_text_only(self.reranker, question, hits) if self.text_only else rerank(self.reranker, question, hits)
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

    def with_next_page(self, hits: List[Hit]) -> List[Hit]:
        """The hits, each one near the end of a page that stops mid-list or mid-table followed by the next page's start.

        with_following adds one chunk for the top two hits only, and that chunk is
        often still on the same page: the FHWA guide's eight policy issues (held-out
        wztc-h033) reached the model as the five on printed p.3-13, and the three on
        3-14 never did. In DAR-732, 5 of the 7 incomplete answers were such lists.

        Every hit counts, at any rank. A hit at most SAME_PAGE_REACH chunks before
        its page's last chunk brings the chunks up to that last one and, when the
        list, table or sentence there runs over (runs_over), the next page's first
        chunk. The same holds backwards: a hit near the start of a page that
        continues the previous one brings that page's last chunk (held-out
        wztc-h032: the search found the list's second page). A hit further into
        its page brings nothing: the page break is not what matched. Chunks the
        hits already hold are not added twice. Each added chunk carries the score
        of the hit that brought it, so the hit's rank still orders the passages.
        """
        seen = {id(h.chunk) for h in hits}
        out: List[Hit] = []
        for hit in hits:
            out.append(hit)
            for chunk in self._from_previous_page(hit.chunk) + self._to_next_page(hit.chunk):
                if id(chunk) not in seen:
                    seen.add(id(chunk))
                    out.append(Hit(hit.score, chunk))
        return out

    def _preceding(self, chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The chunk before this one in the same document (never a figure chunk), or None."""
        i = self.index.position(chunk)
        if is_figure(chunk) or i <= 0 or i >= len(self.index.chunks):
            return None
        before = self.index.chunks[i - 1]
        return before if before.get("source") == chunk.get("source") and not is_figure(before) else None

    def _from_previous_page(self, chunk: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The chunks from the previous page's last one up to `chunk`, when that page's list or table runs onto this one.

        The mirror of _to_next_page: the FHWA guide's example web-site contents
        (held-out wztc-h032) start on printed p.A-10 and end on A-11, and the
        search found A-11.
        """
        chain: List[Dict[str, Any]] = []
        current = chunk
        for _ in range(SAME_PAGE_REACH + 1):
            before = self._preceding(current)
            if before is None or _last_page(before) != current.get("page"):
                break
            chain.append(before)
            current = before
        else:
            return []  # the page starts before the reach
        if (before is None or _last_page(before) != (current.get("page") or 0) - 1
                or not runs_over(before.get("text"), current.get("text"))):
            return []
        return chain + [before]

    def _to_next_page(self, chunk: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The chunks from after `chunk` to the next page's first one, when its page ends open; else none."""
        chain: List[Dict[str, Any]] = []
        current = chunk
        for _ in range(SAME_PAGE_REACH + 1):
            after = self.index.following(current)
            if after is None or after.get("page") != _last_page(current):
                break
            chain.append(after)
            current = after
        else:
            return []  # the page goes on past the reach
        if (after is None or after.get("page") != _last_page(current) + 1
                or not runs_over(current.get("text"), after.get("text"))):
            return []
        return chain + [after]

    def page_continues(self, chunk: Dict[str, Any]) -> bool:
        """Whether the chunk is the last of its page, its list or table goes on, and the next page is missing (DAR-736).

        as_passages asks this of a passage's last part: had the next page's first
        chunk been among the hits, it would have been merged after it. When the
        next page is in the index, runs_over decides; when it is not (a page with
        no text, the end of the document), the page must end on a line that
        leads on ("; and", ":", a table row). The passage is then shown with a
        note that it may go on.
        """
        if is_figure(chunk):
            return False
        after = self.index.following(chunk)
        if after is not None and after.get("page") == _last_page(chunk):
            return False  # not the page's last chunk
        if after is not None and after.get("page") == _last_page(chunk) + 1:
            return runs_over(chunk.get("text"), after.get("text"))
        return leads_on(chunk.get("text"))

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
        return [self._mark_continues(p) for p in passages]

    def _mark_continues(self, passage: Hit) -> Hit:
        """The passage with `continues` set when its last part ends a page open and the next page isn't in the index.

        A copy: the index's own chunks are never changed. A single chunk keeps
        itself as its only part, so callers that match parts by identity still find it.
        """
        parts = passage.chunk.get("parts") or [passage.chunk]
        if not self.page_continues(parts[-1]):
            return passage
        return Hit(passage.score, dict(passage.chunk, parts=parts, continues=True))


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


def _last_page(chunk) -> int:
    """The last PDF page a chunk is on (a table joined over a page break has page_end)."""
    return chunk.get("page_end") or chunk.get("page") or 0


def _page_key(chunk) -> Tuple:
    return (chunk.get("source"), chunk.get("page"), chunk.get("page_end"))


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
