"""Answer a question from one division's documents, with citations.

The flow for one question:

1. retrieve the asked ("target") division's best passages, and only theirs;
2. ask the model to answer from those passages alone, citing them as [n];
3. keep the passages the answer cites, renumbered 1..m in order of first
   mention (one source per document page), with document title, PDF page
   (and the number printed on the page, when it differs), section and a link
   to the public PDF at that page.

When the model says the passages don't answer the question, the next model is
asked once more with the passages ranked after them added (DAR-662). If it
finds nothing either, the reply is a refusal that names the division's
documents and shows no sources; if another division's documents look
relevant, it suggests asking that division instead.
An answer that cites none of the passages is kept and marked `uncited`, so the
page can flag it ("No source cited") instead of hiding it (DAR-629).

Every number the answer states is checked against the passages it cites
(verify.py, DAR-659). When one is missing, the model is asked once more with a
stricter rule, time allowing, and the numbers still missing from the final
answer are returned as `unverified` for the page to flag.

With NUMBER_AGREEMENT on (agreement.py, DAR-663), an answer that states
numbers is also given to a second free model's answer on the same passages,
time allowing: a number read from the wrong cell is on the cited page, so the
check above passes it, but the two models seldom misread the same cell. The
first answer's numbers the second contradicts are added to `unverified`.

answer() waits for the model's whole reply; answer_stream() passes the text on
as it is written. Both grade, retry and refuse the same way.

The asker's own division only shapes the wording (who the answer is for); its
documents are never searched.

A follow-up question comes with the conversation so far (the page keeps it):
the search runs on the previous question plus the follow-up, and the prompt
shows the last turns only to explain what the question refers to. Facts and
citations still come from the new passages alone.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from .agreement import SecondOpinion, answer_numbers, second_opinion, second_opinion_models
from .divisions import BY_ID, DIVISIONS, Division, document_for
from .index_file import Hit
from .llm import Completion, LLMError, OpenRouterClient
from .pages_static import image_url
from .retrieval import DEFAULT_CANDIDATES, DEFAULT_MAX_CHUNKS_PER_PAGE, Retriever, _page_key, is_table
from .timing import StepTimer, timed
from .verify import unverified_numbers

# emit(event, data): one server-sent event of a streamed answer ("step", "delta", "replace").
Emit = Callable[[str, Dict[str, Any]], None]
# One model call: (messages, models) -> the reply; models None means the configured list.
_Call = Callable[..., Awaitable[Completion]]

NOT_FOUND = "NOT_IN_DOCUMENTS"
# Cross-encoder (ms-marco MiniLM) score above which another division's best
# passage counts as relevant enough to suggest asking that division instead.
SUGGEST_THRESHOLD = 0.0
# Vector hits of another division reranked for the suggestion. Against 20, every
# yes/no decision on 70 question-division pairs was the same from 8 up (with 5,
# the open-cut trench question asked of Work Zone lost its "ask Utilities");
# reranking 20 added about 4.6 s to every refusal on Vercel.
SUGGEST_CANDIDATES = 10
# Time a suggestion check for one more division needs: an embedding plus 10
# reranks, about 2.3 s on Vercel by the figure above. With a third division
# (TMSD, DAR-622) a refusal checks two divisions, and a retry may end only
# RETRY_MARGIN_SECONDS before the deadline, so later checks are skipped rather
# than letting the refusal run past it.
SUGGEST_MIN_SECONDS = 3.0
# A refusal is retried once, with the next ranked passages added (SECOND_LOOK_PASSAGES),
# when the best passage's reranker score is at least this. It was 1.0 while the retry
# only re-read the same passages: then questions the documents don't answer scored
# -9.4 to -3.5. On the locked set the score no longer separates the two (DAR-662): the
# tuning split's 7 questions that must be refused scored -1.51 to 3.96, and answerable
# questions refused without a retry scored -1.61 (utilities-028, a footnote 9th in the
# ranking), -0.97, -0.62 and 0.48 (wztc-037, a scanned page 12th). The bar now only keeps
# the refusal of a question nothing in the division is close to fast.
RETRY_MIN_SCORE = -2.0
# Chunks ranked after the top k that the retry after a refusal reads too, taken in rank
# order from all the reranked candidates, skipping table chunks of a page that already
# gave SECOND_LOOK_TABLE_CHUNKS_PER_PAGE. Of the 16 answerable questions the final DAR-652
# run refused, only 2 had the answer in the top 5; 11 more have it among the chunks this
# picks (wztc-034 7th, wztc-019's row on the next page 8th, wztc-037's scanned page 12th;
# docs/redo-reports/dar-662-refusals.md). Without the table cap the next 15 ranks miss
# "What are the NC-PCB dimensions?": 12 labelled-row chunks of one Standard Specifications
# table ("WASHER DIMENSIONS") rank 1 to 12, and the TMP manual's sentence giving the
# barrier's size is 34th. They cost nothing to fetch: the reranker has scored all the
# candidates already. The first answer still reads only the top k (TOP_K).
SECOND_LOOK_PASSAGES = 15
SECOND_LOOK_TABLE_CHUNKS_PER_PAGE = DEFAULT_MAX_CHUNKS_PER_PAGE
# How far down the ranking the retrieval keeps hits for the second look: at most the
# reranker's default candidate pool (retrieval.DEFAULT_CANDIDATES), and never more than the
# retriever's own pool (RERANK_CANDIDATES), so nothing more is searched or reranked.
SECOND_LOOK_RANKED = DEFAULT_CANDIDATES
RETRY_MIN_SECONDS = 15.0
# The retry stops this long before the request's deadline so the refusal can still be returned.
RETRY_MARGIN_SECONDS = 1.0
# An answer with a number missing from its cited passages is asked again with
# NUMBERS_RULE when at least this much of the request is left: the second call
# is a whole answer, like the retry, and the retry's 15 s held for free models.
RECHECK_MIN_SECONDS = RETRY_MIN_SECONDS
# The second model's answer for the number agreement check (NUMBER_AGREEMENT, DAR-663) is a
# whole answer too, so it needs the same time left; with less it is skipped, not cut off.
AGREEMENT_MIN_SECONDS = RETRY_MIN_SECONDS
# ... and is given at most this long: the answer's sources and flags wait for it (they come with
# the checked answer), and the free models answered the tuning split's questions in 2-17 s.
AGREEMENT_MAX_SECONDS = 20.0
EXCERPT_CHARS = 700
# The best hits also bring the next chunk of their document (see Retriever.with_following).
FOLLOWING_FOR_TOP = 2
# Follow-ups (DAR-619) are understood without an extra model call: the search
# runs on the previous question plus the follow-up, and the prompt carries the
# last few turns. The page sends at most this many already; the server keeps
# only these too, whatever arrives. Earlier answers are clipped because they
# only say what "it" or "that" refers to; the facts come from the new passages.
HISTORY_TURNS = 3
HISTORY_ANSWER_CHARS = 1500
# The previous question is clipped so a long one can't push the follow-up past
# the 512 tokens bge-small and the reranker read: the follow-up comes after it in
# the search text. 500 characters plus a follow-up of at most MAX_QUESTION_CHARS
# (500 by default) is about 250 tokens of English; a forged 5,000-character
# history question would otherwise fill the window on its own.
HISTORY_QUESTION_CHARS = 500

SYSTEM_PROMPT = """You answer questions for North Carolina Department of Transportation (NCDOT) staff.
You are answering on behalf of the {target_name} division ({target_unit}), using only numbered passages from its documents.
{asker_line}

Rules:
1. Use only the numbered passages. Do not use outside knowledge, and do not guess or fill gaps.
2. Cite the passage that supports each sentence inline, like [1] or [2][3]. Every sentence that states a fact, number or requirement needs a citation.
3. If the passages do not answer the question, reply with exactly {not_found} and nothing else.
4. If the passages answer only part of the question, answer that part with citations and say plainly which part the documents don't cover.
5. When reading a table, find the row and the column that match the question, and take the unit from that column's header. Say which row and column labels you used, answer in the units the question uses, and always state the unit.
6. Start with the direct answer. Keep it short: one to four sentences, or a short list when there are several requirements. Use plain language.
7. Don't mention "passages" or "context"; refer to the document by name if needed."""

# Rules added after the fixed ones, numbered from 8 in this order, only when they
# apply, so a first question without printed page numbers gets exactly the
# prompt the known-page checks were run with.
# Added when a passage's heading shows a printed page (DAR-654): a reader checks
# the answer against the number printed on the page, so the answer must say it.
PAGE_RULE = """When you mention a page, write it exactly as the passage's heading does, for example "p.13 (PDF page 37)": the first number is the one printed on the page, the second is the PDF reader's page index."""
# Added when the question comes with earlier turns.
HISTORY_RULE = """The earlier conversation, when shown, is only there to understand what the question refers to (for example "it" or "that barrier"). It is not a source: take every fact from the numbered passages and cite them, never from the earlier answers. If the passages do not answer the question, reply with exactly {not_found}, even if the earlier conversation did."""

USER_PROMPT = """{history}Passages from the {target_name} division's documents:

{context}

Question: {question}"""

# Asked after an answer stated numbers its cited passages don't contain (DAR-659).
# The model sees its first answer and which numbers were not found, so it can
# re-read the table instead of rephrasing the same cell.
NUMBERS_RULE = """These numbers in your answer are not in the passages you cited: {numbers}.
Answer the question again from the passages. For every number, quote the row label, the column header, the value and its unit exactly as the passage writes them, and the page, with its citation. State only numbers that appear in the passages; do not convert, round or calculate. If the passages do not answer the question, reply with exactly {not_found} and nothing else."""

# Asked once after an answer that cites no passage. In the DAR-652 final run 72 of
# the 82 answers whose cited page was wrong cited nothing at all: the free model
# replied with the bare value ("5 feet"), right 69 times, with no [n] to show where it came from.
CITE_RULE = """Your answer has no citation, so the reader cannot check it.
Answer the question again from the passages. Put the number of the passage that supports each sentence right after it, even when the answer is a single value, for example: "The minimum is 5 ft [2]." If the passages do not answer the question, reply with exactly {not_found} and nothing else."""

# Asked after a refusal, with the passages ranked after the first ones (DAR-662). The
# model sees its own refusal, so it reads the new passages and looks again at the first
# ones instead of answering a new question. The one refusal with the answer readable in
# the top 5 was a table cell (wztc-029: the lead unit "WZTCU" in a cell of a wide table),
# so the rule names table cells, figure text and notes.
SECOND_LOOK_RULE = """More passages from the {target_name} division's documents, numbered after the first ones:

{context}

Look again for the answer in all the passages, [1] to [{last}]. Read table rows and cells, text taken from figures and drawings, and notes under tables too: their text can have broken spacing or columns out of order. If a passage states the answer, answer the question from it with citations, following the rules above. If none does, reply with exactly {not_found} and nothing else."""

HISTORY_PROMPT = """Earlier conversation, oldest first (only to understand what the question refers to; not a source):

{turns}

"""

# One bracketed citation: "[1]", "[1, 2]", "[1; 2]", "[1-3]", "[1–3]", and the
# lenticular/full-width brackets some models use: "【2】", "［2］".
_CITATION = re.compile(r"[\[【［]\s*(\d+(?:\s*[,;\-–]\s*\d+)*)\s*[\]】］]")
_EMPTY_CITATION = re.compile(r"\s*[\[【［]\s*(?:none|n/?a)\s*[\]】］]", re.IGNORECASE)
_RANGE = re.compile(r"(\d+)\s*[\-–]\s*(\d+)")
_MARKDOWN_NOISE = re.compile(r"<!--.*?-->|\*\*|__|^#{1,6}\s*|<br>|</?(?:mark|u|sup|sub)>", re.MULTILINE | re.DOTALL)


@dataclass(frozen=True)
class Source:
    n: int
    division: str
    title: str
    page: Optional[int]
    page_end: Optional[int]
    section: Optional[str]
    url: str
    excerpt: str
    # The number printed on the page (DAR-654), when the index knows it: `page` is the PDF
    # reader's index, which the link uses, but a reader checking the manual sees the printed
    # one (Dr. Namian read "page 37" as wrong because the page prints "13").
    printed_page: Optional[str] = None
    printed_page_end: Optional[str] = None
    image: Optional[str] = None  # site-relative URL of the page's image, when rendered (DAR-654)

    def as_dict(self) -> Dict:
        return {
            "n": self.n, "division": self.division, "title": self.title, "page": self.page,
            "page_end": self.page_end, "section": self.section, "url": self.url, "excerpt": self.excerpt,
            "printed_page": self.printed_page, "printed_page_end": self.printed_page_end,
            "image": self.image,
        }


@dataclass
class Answer:
    answer: str
    refused: bool
    sources: List[Source] = field(default_factory=list)
    model: Optional[str] = None
    suggest: List[str] = field(default_factory=list)  # division ids worth asking instead
    retried: bool = False  # a refusal was followed by a second model call
    first_model: Optional[str] = None  # the model that answered the first call (differs from `model` after a retry)
    uncited: bool = False  # an answer (not a refusal) that cites none of the passages
    unverified: List[str] = field(default_factory=list)  # numbers not found in the cited passages (verify.py)
    # How an answer the model first gave without citations got its sources: "asked_again"
    # (CITE_RULE) or "number_match" (number_source); None when the model cited on its own.
    citation_fix: Optional[str] = None
    # The number agreement check (agreement.py, DAR-663), when it ran and the second model answered
    # with numbers; its `disagreed` numbers are also in `unverified`.
    second_opinion: Optional[SecondOpinion] = None

    def as_dict(self) -> Dict:
        return {
            "answer": self.answer,
            "refused": self.refused,
            "uncited": self.uncited,
            "unverified": list(self.unverified),
            "sources": [s.as_dict() for s in self.sources],
            "model": self.model,
            "first_model": self.first_model,
            "retried": self.retried,
            "citation_fix": self.citation_fix,
            "second_opinion": self.second_opinion.as_dict() if self.second_opinion else None,
            "suggest": [{"id": d, "name": BY_ID[d].name} for d in self.suggest],
        }


class Passages(list):
    """The passages the model reads (a list of Hit), with the ranked hits after them as `more`.

    Only the retry after a refusal reads `more` (SECOND_LOOK_PASSAGES). A plain
    list of hits has none, and its retry re-reads the same passages.
    """

    def __init__(self, hits: Sequence[Hit] = (), more: Sequence[Hit] = ()):
        super().__init__(hits)
        self.more = list(more)


def _locator(hit: Hit) -> str:
    chunk = hit.chunk
    document = document_for(chunk.get("source") or "")
    parts = [document.title if document else (chunk.get("source") or "unknown document")]
    if chunk.get("page"):
        parts.append(_pages(chunk))
    if chunk.get("section"):
        parts.append(f"section {chunk['section']}")
    return ", ".join(parts)


def _pages(chunk: Dict) -> str:
    """The page label: "PDF page 37", or "p.13 (PDF page 37)" when the page prints another number.

    Both numbers are given because readers check citations against the printed
    one (Dr. Namian read "page 37" as wrong: the page prints "13") while the
    link can only open the PDF at its index. The model is told to write pages
    the same way (rule 8).
    """
    page, page_end = chunk.get("page"), chunk.get("page_end")
    pdf = f"PDF pages {page}–{page_end}" if page_end and page_end != page else f"PDF page {page}"
    if not _shows_printed_page(chunk):
        return pdf
    printed, printed_end = printed_pages(chunk)
    return f"pp.{printed}–{printed_end} ({pdf})" if printed_end else f"p.{printed} ({pdf})"


def _shows_printed_page(chunk: Dict) -> bool:
    """Whether the chunk's page label names a printed page: it has one, and it isn't just the PDF index again."""
    printed, printed_end = printed_pages(chunk)
    page, page_end = chunk.get("page"), chunk.get("page_end")
    return printed is not None and (printed, printed_end or printed) != (str(page), str(page_end or page))


def printed_pages(chunk: Dict) -> Tuple[Optional[str], Optional[str]]:
    """The printed page number of a chunk, and the last one of a merged passage; (None, None) when the index has none.

    A merged passage (Retriever.as_passages) copies the first chunk's
    `printed_page` and keeps the chunks as `parts`, so its last page is the
    last part's; narrow() sets `printed_page_end` on the chunk it builds
    instead. The end is None when it is the same number, like `page_end`. An
    empty label (PyMuPDF's get_label() for an unlabelled page) counts as none,
    and so does a merged passage whose last page has none: "p.12 (PDF pages
    36–38)" for a run ending on an unnumbered plate would claim all of it is
    printed page 12.
    """
    first = chunk.get("printed_page")
    if first is None or first == "":
        return None, None
    parts = chunk.get("parts") or []
    # A table joined over a page break (DAR-655) is one chunk with its own printed_page_end.
    tail = parts[-1] if len(parts) > 1 else None
    last = chunk.get("printed_page_end") or (tail.get("printed_page_end") or tail.get("printed_page") if tail else first)
    if last is None or last == "":
        return None, None
    return str(first), None if str(last) == str(first) else str(last)


def recent_turns(history: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """The last HISTORY_TURNS turns of the conversation, oldest first."""
    return list(history)[-HISTORY_TURNS:]


def _clip(text: str, limit: int) -> str:
    """The text in at most `limit` characters (plus " …" when cut), never an empty prefix.

    It is cut after the last whole word when one ends near the limit; text with
    no space there (a pasted URL or part number) is cut at the limit itself.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.8 else cut) + " …"


def _history_text(history: Sequence[Dict[str, str]]) -> str:
    """The earlier turns for the user message; empty when there are none.

    Their [n] markers are removed: they numbered the earlier answer's passages,
    and left in they would read as citations of this question's passages. A turn
    with an empty answer is a question asked of another division, which the page
    sends when one of its "Ask … instead" buttons is used; only its question is shown.
    """
    turns = []
    for turn in recent_turns(history):
        text = f"Earlier question: {_clip(turn.get('question') or '', HISTORY_QUESTION_CHARS)}"
        answer = _CITATION.sub("", _EMPTY_CITATION.sub("", turn.get("answer") or ""))
        answer = _clip(re.sub(r"[ \t]+([.,;:])", r"\1", answer), HISTORY_ANSWER_CHARS)
        turns.append(f"{text}\nEarlier answer: {answer}" if answer else text)
    return HISTORY_PROMPT.format(turns="\n\n".join(turns)) if turns else ""


def passage_text(chunk: Dict) -> str:
    """A passage as the model reads it: each part's text after its context line, once per page.

    The context line names the page's figure and table captions, so a chunk of
    numbers split away from its caption still says which table it is (the TMP
    manual's asphalt and concrete deflection tables, pp. 37-38).
    """
    out, last = [], None
    for part in chunk.get("parts", [chunk]):
        context = part.get("context")
        out.append(f"{context}\n{part['text']}" if context and context != last else part["text"])
        last = context
    return "\n\n".join(out)


def build_messages(question: str, asker: Division, target: Division, hits: List[Hit],
                   history: Sequence[Dict[str, str]] = ()) -> List[Dict[str, str]]:
    """The system and user messages for one question.

    `history` is the conversation so far ([{"question", "answer"}], oldest
    first). Its last HISTORY_TURNS turns go before the passages, with a rule
    that they only explain what the question refers to.
    """
    if asker.id == target.id:
        asker_line = f"The person asking also works in {target.name}."
    else:
        asker_line = (
            f"The person asking works in a different division, {asker.name} ({asker.unit}), and may not know "
            f"{target.name}'s terms; explain them briefly only where the passages do."
        )
    earlier = _history_text(history)
    system = SYSTEM_PROMPT.format(
        target_name=target.name, target_unit=target.unit, asker_line=asker_line, not_found=NOT_FOUND
    )
    extra = [PAGE_RULE] if any(_shows_printed_page(hit.chunk) for hit in hits) else []
    if earlier:
        extra.append(HISTORY_RULE.format(not_found=NOT_FOUND))
    system += "".join(f"\n{n}. {rule}" for n, rule in enumerate(extra, 8))
    user = USER_PROMPT.format(history=earlier, target_name=target.name, context=_numbered(hits), question=question)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _numbered(hits: Sequence[Hit], start: int = 1) -> str:
    """The passages as the prompt shows them, numbered from `start`: "[n] (locator)" and the text."""
    return "\n\n---\n\n".join(f"[{n}] ({_locator(hit)})\n{passage_text(hit.chunk)}" for n, hit in enumerate(hits, start))


def _marker_numbers(marker: "re.Match[str]", n_hits: int) -> List[int]:
    """Valid passage numbers in one citation marker; out-of-range and malformed parts are dropped."""
    numbers: List[int] = []
    for part in re.split(r"\s*[,;]\s*", marker.group(1)):
        span = _RANGE.fullmatch(part)
        if span:
            low, high = int(span.group(1)), int(span.group(2))
            candidates = range(low, high + 1) if low <= high <= n_hits else []
        else:
            candidates = [int(part)] if part.isdigit() else []
        numbers += [n for n in candidates if 1 <= n <= n_hits and n not in numbers]
    return numbers


def cited_numbers(text: str, n_hits: int) -> List[int]:
    """1-based passage numbers cited in the text, in order of first mention."""
    cited: List[int] = []
    for marker in _CITATION.finditer(text):
        cited += [n for n in _marker_numbers(marker, n_hits) if n not in cited]
    return cited


def _excerpt(text: str) -> str:
    clean = " ".join(_MARKDOWN_NOISE.sub(" ", text).split())
    return clean if len(clean) <= EXCERPT_CHARS else clean[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"


def _source_for(hit: Hit, n: int) -> Source:
    chunk = hit.chunk
    document = document_for(chunk.get("source") or "")
    page = chunk.get("page")
    url = document.url if document else ""
    if url and page:
        url = f"{url}#page={page}"
    printed, printed_end = printed_pages(chunk)
    return Source(
        n=n,
        division=chunk.get("division") or "",
        title=document.title if document else (chunk.get("source") or "Unknown document"),
        page=page,
        page_end=chunk.get("page_end"),
        section=chunk.get("section"),
        url=url,
        excerpt=_excerpt(chunk.get("text") or ""),
        printed_page=printed,
        printed_page_end=printed_end,
        image=image_url(chunk),
    )


_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*")
_STOPWORDS = frozenset(
    "the and for with that this from are any all not may must shall should will within than then into "
    "per its has have been was were when where which who what how can each other such only also".split()
)
# A part of a merged passage is cited when it holds at least half of the
# best part's overlap with the citing sentences.
_PART_SHARE = 0.5


def _words(text: str) -> set:
    return {w for w in _WORD.findall(text.lower()) if (len(w) > 2 or w[0].isdigit()) and w not in _STOPWORDS}


def _citing_sentences(text: str, n: int, n_hits: int) -> str:
    sentences = re.split(r"(?<=[.!?\]])\s+(?=[A-Z0-9])", text)
    return " ".join(s for s in sentences if any(n in _marker_numbers(m, n_hits) for m in _CITATION.finditer(s)))


def narrow(chunk: Dict, sentences: str) -> Dict:
    """The part of a merged passage (Retriever.as_passages) that the citing sentences draw on.

    Merged passages help the model read a rule that runs across pages, but a
    citation should name the page(s) the answer came from, not the whole run.
    Parts are scored by how many of the sentences' words they contain; the
    pages of the parts close to the best score are kept.
    """
    parts = chunk.get("parts") or []
    if len(parts) < 2:
        return chunk
    words = _words(_CITATION.sub(" ", sentences))
    scores = [len(words & _words(part["text"])) for part in parts]
    best = max(scores)
    if best == 0:
        return chunk
    kept = [part for part, score in zip(parts, scores) if score >= _PART_SHARE * best]
    # A kept part that is a table joined over a page break spans page..page_end on its own.
    pages = [p for part in kept for p in (part.get("page"), part.get("page_end")) if p]
    sections = [s for part in kept if part.get("section") for s in part["section"].split("; ")]
    narrowed = dict(kept[0], text="\n\n".join(part["text"] for part in kept), section="; ".join(dict.fromkeys(sections)) or None)
    narrowed.pop("page_end", None)
    if pages:
        narrowed["page"] = min(pages)
        if max(pages) != min(pages):
            narrowed["page_end"] = max(pages)
    # The printed pages of the first and last kept parts (kept[0]'s is already copied). If
    # either is unnumbered, drop both rather than label a run of pages with one printed page.
    printed_first, (last_start, last_end) = printed_pages(kept[0])[0], printed_pages(kept[-1])
    printed_last = last_end or last_start
    if printed_first is None or printed_last is None:
        narrowed.pop("printed_page", None)
    elif printed_last != printed_first:
        narrowed["printed_page_end"] = printed_last
    return narrowed


def attach_sources(text: str, hits: List[Hit]) -> Tuple[str, List[Source]]:
    """Renumber the answer's citations 1..m and build one Source per cited document page.

    Passages from the same page of the same document share one number.
    Citations of passages that don't exist are removed.
    """
    text = _EMPTY_CITATION.sub("", text)
    new_number: Dict[int, int] = {}
    by_page: Dict[Tuple[str, Optional[int], Optional[int]], int] = {}
    sources: List[Source] = []
    for old in cited_numbers(text, len(hits)):
        chunk = narrow(hits[old - 1].chunk, _citing_sentences(text, old, len(hits)))
        key = (chunk.get("source") or "", chunk.get("page"), chunk.get("page_end"))
        if key not in by_page:
            by_page[key] = len(sources) + 1
            sources.append(_source_for(Hit(hits[old - 1].score, chunk), by_page[key]))
        new_number[old] = by_page[key]

    def rewrite(marker: "re.Match[str]") -> str:
        numbers = list(dict.fromkeys(new_number[n] for n in _marker_numbers(marker, len(hits)) if n in new_number))
        return "".join(f"[{n}]" for n in numbers)

    text = _CITATION.sub(rewrite, text)
    text = re.sub(r"(\[\d+\])(?:\s*\1)+", r"\1", text)  # "[1][1]" when two passages share a page
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text)  # "word [9]." with [9] removed -> "word."
    return text.strip(), sources


# Up to this many documents, a refusal names them; beyond it, it counts them. With the
# 50-document stress test (DAR-621) a division has up to 20, and listing every title made a
# refusal about 2,000 characters long; the page's document panel lists them anyway.
_REFUSAL_TITLES = 3


def refusal_text(target: Division, suggest: List[str]) -> str:
    if len(target.documents) <= _REFUSAL_TITLES:
        searched = "; ".join(d.title for d in target.documents)
    else:
        searched = f"{len(target.documents)} documents"
    text = f"I couldn't find an answer to that in the {target.name} documents ({searched})."
    if len(suggest) == 1:
        name = BY_ID[suggest[0]].name
        text += f" The {name} documents look more relevant: try asking {name} instead."
    elif suggest:
        # Listed, not joined with "or": "Transportation Mobility and Safety" already has an "and" in it.
        names = "; ".join(BY_ID[d].name for d in suggest)
        text += f" Other divisions' documents look more relevant; try asking one of them instead: {names}."
    else:
        text += " Try rephrasing the question, or ask the division that owns the topic."
    return text


log = logging.getLogger(__name__)


def _grade(raw: str, hits: List[Hit]) -> Tuple[str, List[Source]]:
    """The answer text and its sources.

    Empty text means the model said the documents don't answer the question.
    Text without sources is an answer that cites none of the passages: it is
    kept and flagged, not turned into a refusal (DAR-629). A reply that uses
    NOT_FOUND inside a sentence and cites nothing ("I'm sorry, NOT_IN_DOCUMENTS")
    is a refusal worded around the marker, not an answer.
    """
    if _lead(raw).startswith(NOT_FOUND):
        return "", []
    text, sources = attach_sources(raw.replace(NOT_FOUND, ""), hits)
    if NOT_FOUND in raw and not sources:
        return "", []
    return text, sources


def _unverified(raw: str, text: str, hits: List[Hit], asked: str) -> List[str]:
    """The numbers of a graded answer `text` missing from the passages `raw` cites.

    `asked` is the question with the earlier turns' questions: numbers the
    visitor gave are not the documents' to verify. An answer citing nothing is
    checked against all the passages it was given, so its numbers are still
    checked; it is already flagged "No source cited". The locator ("TMP Design
    Manual, PDF page 37") verifies a bare page number the answer names.
    """
    cited = cited_numbers(_EMPTY_CITATION.sub("", raw.replace(NOT_FOUND, "")), len(hits))
    shown = [hits[n - 1] for n in cited] or hits
    return unverified_numbers(text, [passage_text(hit.chunk) for hit in shown], asked,
                              labels=[_locator(hit) for hit in shown])


def number_source(text: str, hits: List[Hit], asked: str) -> Optional[int]:
    """The passage (1-based) that alone holds every number of an uncited answer, or None.

    Only numbers the question didn't give count, and only when exactly one passage
    has them all: a bare "5 feet" was in 2 to 5 of the passages for most uncited
    answers of the DAR-652 final run, and citing the best-ranked of those picked the
    wrong page 19 times in 62. With exactly one, it picked the right page 33 times in 34.
    """
    if not unverified_numbers(text, [], asked):
        return None
    holding = [n for n, hit in enumerate(hits, 1)
               if not unverified_numbers(text, [passage_text(hit.chunk)], asked, labels=[_locator(hit)])]
    return holding[0] if len(holding) == 1 else None


def with_marker(text: str, n: int) -> str:
    """The answer with "[n]" at its end, before a closing full stop: "The minimum is 5 ft [2]."."""
    return re.sub(r"\s*([.!?]?)\s*$", rf" [{n}]\1", text, count=1)


def _lead(text: str) -> str:
    """The text without leading whitespace and Markdown emphasis, where a reply that refuses starts with NOT_FOUND."""
    return text.lstrip(" \t\r\n*_`")


def _marker_start(text: str) -> int:
    """How many characters at the end of `text` could be the beginning of NOT_FOUND."""
    for size in range(min(len(NOT_FOUND) - 1, len(text)), 0, -1):
        if text.endswith(NOT_FOUND[:size]):
            return size
    return 0


# A complete citation marker in streamed text, with the spaces before it ("feet [3]." shows as "feet.").
_STREAMED_CITATION = re.compile(r"[ \t]*[\[【［]\s*(?:\d+(?:\s*[,;\-–]\s*\d+)*|none|n/?a)\s*[\]】］]", re.IGNORECASE)
# What the end of streamed text holds back: trailing spaces, and a bracket not yet closed
# that may be the start of a citation (short, as markers are).
_OPEN_TAIL = re.compile(r"[ \t]*(?:[\[【［][^\]】］\n]{0,20})?$")


class _VisibleText:
    """Which part of a reply that is still being written can be shown yet.

    The start is held back until it can't be NOT_FOUND, so a refusal's marker
    never flashes on the page, and a reply that starts with it shows nothing
    (_grade makes it a refusal). Further in, the marker is cut out as _grade
    cuts it, holding back a tail that could be its beginning.

    Citation markers are left out too: they carry the prompt's passage
    numbers, which the citation check renumbers ([4] may become [1]), so the
    answer's citations appear only with the checked answer.
    """

    def __init__(self) -> None:
        self._held = ""
        self._flowing = False  # the start is not the marker: text is shown as it comes
        self.refusal = False

    def feed(self, piece: str) -> str:
        """The new text to show after `piece` (often "")."""
        if self.refusal:
            return ""
        self._held += piece
        if not self._flowing:
            head = _lead(self._held)
            if head.startswith(NOT_FOUND):
                self.refusal, self._held = True, ""
                return ""
            if NOT_FOUND.startswith(head):  # "", "**" or e.g. "NOT_IN": could still become the marker
                return ""
            # Leading whitespace goes, as the final answer is stripped; emphasis stays.
            self._flowing, self._held = True, self._held.lstrip()
        text = _STREAMED_CITATION.sub("", self._held.replace(NOT_FOUND, ""))
        tail = _OPEN_TAIL.search(text)
        cut = min(tail.start() if tail else len(text), len(text) - _marker_start(text))
        self._held = text[cut:]
        return text[:cut]

    def end(self) -> str:
        """The text still held back once the reply is complete."""
        if self.refusal or not self._flowing:
            rest = "" if self.refusal else self._held.strip()
        else:
            rest = self._held.rstrip()
        self._held = ""
        return _STREAMED_CITATION.sub("", rest.replace(NOT_FOUND, ""))


# The steps the page shows while it answers (DAR-629), in order, with the
# StepTimer steps each is made of. "read" includes loading the models on a cold
# instance, so that wait shows as the first step instead of a pause before it.
LIVE_STEPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("read", ("model_load", "embed")),
    ("search", ("search",)),
    ("rerank", ("rerank",)),
    ("write", ("llm",)),
    ("check", ("citations",)),
    ("retry", ("retry",)),
    ("recite", ("recite",)),
    ("recheck", ("recheck",)),
    ("agree", ("agree",)),
    ("suggest", ("suggest",)),
)

# Steps that run only for some answers (after a refusal, an uncited answer, an
# unverified number, or, for "agree", an answer with numbers while
# NUMBER_AGREEMENT is on), so the page isn't told about them in advance: a step
# left "not started" at the end would read as if the answer stopped short (DAR-636).
OCCASIONAL_STEPS = ("retry", "recite", "recheck", "agree", "suggest")


def live_step_labels(target: Division, passages: int, top_k: int) -> Dict[str, str]:
    """What the page calls each live step; `passages` is how many the search looks through."""
    return {
        "read": "Reading your question",
        "search": f"Searching {target.name} documents ({passages:,} passages)",
        "rerank": f"Picking the {top_k} best passages",
        "write": "Writing the answer",
        "check": "Checking sources",
        "retry": "Double-checking the source…",
        "recite": "Finding the source for the answer…",
        "recheck": "Checking the numbers against the source…",
        "agree": "Asking a second model to check the numbers…",
        "suggest": "Checking whether another division covers it",
    }


class LiveSteps:
    """A StepTimer listener that turns the timer's steps into the steps the page shows.

    A live step starts with the first of its timer steps and is done after the
    last one, with their times added, so its ms are the ones in timing_ms.
    `done` lists the finished ones, [{"id", "label", "ms"}], for the answer's
    payload; with `emit`, each start and finish is also sent as it happens:
    emit("step", {"id", "label", "status": "start" | "done", "ms"}), after
    announce() has sent the expected ones as "pending".
    """

    def __init__(self, labels: Dict[str, str], emit: Optional[Emit] = None):
        self._labels = labels
        self._emit = emit
        self._live = {part: live for live, parts in LIVE_STEPS for part in parts}
        self._last = {live: parts[-1] for live, parts in LIVE_STEPS}
        self._running: Dict[str, int] = {}
        self.done: List[Dict[str, Any]] = []

    def announce(self, rerank: bool) -> None:
        """Send each step expected to run as pending, in order, before the first one starts.

        The page lists every step from the start as not started (DAR-636: on the
        Oct 22 demo a list that grew one step at a time was confusing). rerank runs
        only with a reranker; retry and suggest (OCCASIONAL_STEPS) appear when they start.
        """
        for live, _ in LIVE_STEPS:
            if live in OCCASIONAL_STEPS or (live == "rerank" and not rerank):
                continue
            self._send(live, "pending", 0)

    def __call__(self, step: str, status: str, ms: int) -> None:
        live = self._live[step]
        if status == "start":
            if live not in self._running:
                self._running[live] = 0
                self._send(live, "start", 0)
            return
        self._running[live] = self._running.get(live, 0) + ms
        if step == self._last[live]:
            ms = self._running.pop(live)
            self.done.append({"id": live, "label": self._labels[live], "ms": ms})
            self._send(live, "done", ms)

    def _send(self, live: str, status: str, ms: int) -> None:
        if self._emit:
            self._emit("step", {"id": live, "label": self._labels[live], "status": status, "ms": ms})


def _time_left(deadline: Optional[float], needed: float) -> bool:
    """At least `needed` seconds of the request are left (always, without a deadline).

    More than the margin must be left too, or a second call would get no time
    and be reported as a retry that never ran.
    """
    if deadline is None:
        return True
    left = deadline - time.monotonic()
    return left >= needed and left > RETRY_MARGIN_SECONDS


class Answerer:
    def __init__(self, retriever: Retriever, llm: OpenRouterClient, top_k: int = 5,
                 retry_min_score: Optional[float] = RETRY_MIN_SCORE, retry_min_seconds: float = RETRY_MIN_SECONDS,
                 second_look: int = SECOND_LOOK_PASSAGES, number_agreement: bool = False):
        self.retriever = retriever
        self.llm = llm
        self.top_k = top_k
        self.retry_min_score = retry_min_score  # None: never retry
        self.retry_min_seconds = retry_min_seconds
        self.second_look = second_look  # ranked chunks after the top k for the retry; 0: it re-reads the same passages
        self.number_agreement = number_agreement  # NUMBER_AGREEMENT: a second model checks the numbers (DAR-663)

    def search_query(self, question: str, history: Sequence[Dict[str, str]] = ()) -> str:
        """The text to search with: the previous question plus this one when there is history.

        A follow-up such as "What if it is more than 6 feet from the edge?" says
        nothing about bridge-deck barrier on its own, so searched alone it finds
        other 6-foot rules. Prefixing only the latest question keeps the topic
        without letting older turns outweigh the new question. No model call
        rewrites the question, which keeps follow-ups as fast as first questions.
        The previous question is clipped to HISTORY_QUESTION_CHARS so the
        follow-up after it always stays inside the models' 512-token window.
        """
        turns = recent_turns(history)
        previous = _clip(turns[-1].get("question") or "", HISTORY_QUESTION_CHARS) if turns else ""
        return f"{previous} {question}" if previous else question

    def retrieve(self, question: str, target: Division, timer: Optional[StepTimer] = None,
                 documents: Optional[Sequence[str]] = None, history: Sequence[Dict[str, str]] = ()) -> Passages:
        """The passages for the question from `target`'s documents (only `documents` when given).

        The rest of the reranked pool (_ranked_depth) comes along as the result's
        `more`, for the retry after a refusal. It is fetched in the same search: the
        first top k of a longer ranking of the same pool are the same chunks
        (aggregate_pages only cuts its order to k), so the first answer reads what
        it read before.
        """
        ranked = self.retriever.retrieve(self.search_query(question, history), division=target.id,
                                         k=self._ranked_depth(), timer=timer, sources=documents)
        first = ranked[:self.top_k]
        return Passages(self.retriever.as_passages(self.retriever.with_following(first, top=FOLLOWING_FOR_TOP)),
                        more=ranked[self.top_k:])

    def _ranked_depth(self) -> int:
        """How many ranked hits retrieve() asks for: the top k, plus the rest of the reranked pool for a retry.

        Only the reranked pool: a deeper k would widen the pool itself (Retriever.retrieve
        searches max(k, candidates)), and without a reranker it would widen the fused
        searches, changing the first answer's top k. Nothing deeper is fetched when
        no retry can run (no reranker, RETRY_ON_REFUSAL=off, or second_look 0).
        """
        pool = getattr(self.retriever, "candidates", None)
        if (not self.second_look or self.retry_min_score is None or self.retriever.reranker is None
                or not isinstance(pool, int)):
            return self.top_k
        return max(self.top_k, min(pool, SECOND_LOOK_RANKED))

    def _second_look(self, hits: List[Hit]) -> List[Hit]:
        """Up to `second_look` of the hits ranked after `hits` (their `more`), picked in rank order, as passages.

        as_passages puts them in reading order and merges neighbours, as it does the
        first passages.

        A chunk the first passages already hold, as a following chunk or a merged
        part, is not shown twice under another number. A page gives at most
        SECOND_LOOK_TABLE_CHUNKS_PER_PAGE table chunks, its first ones counted
        too: a table's labelled rows are split into many chunks that score alike,
        and they would otherwise fill the second look with one table.
        """
        shown = {id(part) for hit in hits for part in hit.chunk.get("parts", [hit.chunk])}
        tables: Dict[Tuple, int] = {}
        for hit in hits:
            for part in hit.chunk.get("parts", [hit.chunk]):
                if is_table(part):
                    tables[_page_key(part)] = tables.get(_page_key(part), 0) + 1
        picked: List[Hit] = []
        for hit in getattr(hits, "more", []):
            if len(picked) >= self.second_look:
                break
            if id(hit.chunk) in shown:
                continue
            if is_table(hit.chunk):
                if tables.get(_page_key(hit.chunk), 0) >= SECOND_LOOK_TABLE_CHUNKS_PER_PAGE:
                    continue
                tables[_page_key(hit.chunk)] = tables.get(_page_key(hit.chunk), 0) + 1
            picked.append(hit)
        return self.retriever.as_passages(picked) if picked else []

    def suggest_divisions(self, question: str, target: Division, deadline: Optional[float] = None,
                          refused_by: Sequence[str] = ()) -> List[str]:
        """Other divisions whose best passage clears the reranker's relevance bar.

        `refused_by` are divisions that already refused this question (the page
        sends them after an "Ask … instead"); they are never suggested again.
        Otherwise two divisions whose passages both mention the topic send the
        visitor back and forth: after DAR-621, "lane closure" scored above
        SUGGEST_THRESHOLD in both Work Zone and Utilities, and each refusal
        suggested the other.

        Divisions are checked one after another, and the check stops when less
        than SUGGEST_MIN_SECONDS of the request is left, so a refusal that comes
        late (after a retry) is still returned, without the later suggestions.
        """
        if self.retriever.reranker is None:
            return []
        suggest = []
        for division in DIVISIONS:
            if division.id == target.id or division.id in refused_by:
                continue
            if deadline is not None and deadline - time.monotonic() < SUGGEST_MIN_SECONDS:
                log.info("skipping the remaining division suggestions: too little time left")
                break
            # All the candidates, not k=1: with PAGE_AGGREGATION=sum or MAX_CHUNKS_PER_DOCUMENT the first hit
            # need not be the best-scoring chunk (DAR-657); the retrieval cost is the same either way.
            hits = self.retriever.retrieve(question, division=division.id, k=SUGGEST_CANDIDATES,
                                           candidates=SUGGEST_CANDIDATES)
            if hits and max(h.score for h in hits) >= SUGGEST_THRESHOLD:
                suggest.append(division.id)
        return suggest

    def _worth_retrying(self, hits: List[Hit], deadline: Optional[float]) -> bool:
        """The top reranker score is at least retry_min_score and enough of the request's time is left."""
        if self.retry_min_score is None or self.retriever.reranker is None:
            return False
        if max(hit.score for hit in hits) < self.retry_min_score:
            return False
        return _time_left(deadline, self.retry_min_seconds)

    async def _retry(self, messages: List[Dict[str, str]], first: Completion, hits: List[Hit], target: Division,
                     deadline: Optional[float], call: _Call) -> Optional[Tuple[Completion, str, List[Source],
                                                                             List[Dict[str, str]], List[Hit]]]:
        """Ask once more with the next model, showing it the passages ranked after `hits` too.

        Returns the reply, that reply graded, and the messages and passages it was
        given (the first passages, then the new ones numbered after them), or None
        if the call failed. Without passages ranked after `hits` (SECOND_LOOK_PASSAGES
        0, or none left), the same prompt is asked again.

        Only a cited answer replaces the refusal (see _answer). An uncited answer
        is kept when it is the first reply, but not in place of a refusal: one
        model saying the documents don't cover it and the next answering
        without pointing to a passage is the case most likely to come from
        outside the documents.
        """
        extra = self._second_look(hits)
        wider = list(hits) + extra
        if extra:
            messages = messages + [
                {"role": "assistant", "content": first.text},
                {"role": "user", "content": SECOND_LOOK_RULE.format(
                    target_name=target.name, context=_numbered(extra, len(hits) + 1), last=len(wider),
                    not_found=NOT_FOUND)},
            ]
        models = self.llm.retry_models(first.model)
        log.info("refusal (top score %.2f): retrying %s with %s and %d more passages",
                 max(hit.score for hit in hits), first.model, models[0], len(extra))
        timeout = None if deadline is None else deadline - time.monotonic() - RETRY_MARGIN_SECONDS
        try:
            second = await asyncio.wait_for(call(messages, models=models), timeout=timeout)
        except (LLMError, asyncio.TimeoutError) as exc:
            log.warning("retry failed (%s); keeping the refusal", exc.__class__.__name__)
            return None
        text, sources = _grade(second.text, wider)
        log.info("retry by %s: %s", second.model,
                 "cited answer" if sources else "uncited answer, keeping the refusal" if text else "refused again")
        return second, text, sources, messages, wider

    async def _recheck(self, messages: List[Dict[str, str]], first: Completion, unverified: List[str],
                       hits: List[Hit], asked: str, deadline: Optional[float],
                       call: _Call) -> Optional[Tuple[Completion, str, List[Source], List[str]]]:
        """Ask once more with NUMBERS_RULE: the reply graded with its unverified numbers, or None if the call failed."""
        log.info("answer by %s states numbers not in its cited passages (%s): asking again", first.model,
                 ", ".join(unverified))
        again = messages + [
            {"role": "assistant", "content": first.text},
            {"role": "user", "content": NUMBERS_RULE.format(numbers=", ".join(unverified), not_found=NOT_FOUND)},
        ]
        # The model that wrote the answer is asked to correct it (after a retry, not the one that refused).
        models = [first.model, *[m for m in self.llm.retry_models(first.model) if m != first.model]]
        timeout = None if deadline is None else deadline - time.monotonic() - RETRY_MARGIN_SECONDS
        try:
            second = await asyncio.wait_for(call(again, models=models), timeout=timeout)
        except (LLMError, asyncio.TimeoutError) as exc:
            log.warning("number recheck failed (%s); keeping the first answer", exc.__class__.__name__)
            return None
        text, sources = _grade(second.text, hits)
        still = _unverified(second.text, text, hits, asked) if text else []
        log.info("recheck by %s: %s", second.model,
                 f"cited answer, unverified {still or 'none'}" if sources else "uncited answer" if text else "refused")
        return second, text, sources, still

    async def _recite(self, messages: List[Dict[str, str]], first: Completion, hits: List[Hit],
                      deadline: Optional[float], call: _Call) -> Optional[Tuple[Completion, str, List[Source]]]:
        """Ask once more with CITE_RULE: the reply and that reply graded, or None if the call failed."""
        log.info("answer by %s cites no passage: asking again for citations", first.model)
        again = messages + [
            {"role": "assistant", "content": first.text},
            {"role": "user", "content": CITE_RULE.format(not_found=NOT_FOUND)},
        ]
        models = [first.model, *[m for m in self.llm.retry_models(first.model) if m != first.model]]
        timeout = None if deadline is None else deadline - time.monotonic() - RETRY_MARGIN_SECONDS
        try:
            second = await asyncio.wait_for(call(again, models=models), timeout=timeout)
        except (LLMError, asyncio.TimeoutError) as exc:
            log.warning("citation recheck failed (%s); keeping the first answer", exc.__class__.__name__)
            return None
        text, sources = _grade(second.text, hits)
        log.info("citation recheck by %s: %s", second.model,
                 "cited answer" if sources else "uncited answer" if text else "refused")
        return second, text, sources

    async def _second_opinion(self, messages: List[Dict[str, str]], first: Completion, text: str, hits: List[Hit],
                              asked: str, deadline: Optional[float], timer: Optional[StepTimer],
                              avoid: Sequence[str] = ()) -> Optional[SecondOpinion]:
        """The number agreement check (agreement.py), when it is on and worth a call; None otherwise.

        It runs after the answer is final (retry, recite and recheck done), not
        alongside the first call: only an answer that states numbers needs it,
        a refusal needs none, and the numbers to compare are the final answer's.
        Run alongside, every question would spend a second call of the free
        models' shared daily quota. The cost is the second call's time on
        numeric answers only (at most AGREEMENT_MAX_SECONDS): the streamed text
        is already on the page, but its citations, sources and flags come with
        the checked answer, after it. `avoid` are models that refused this
        question before a retry answered it.
        """
        if not self.number_agreement:
            return None
        first_numbers = answer_numbers(text, asked)
        models = second_opinion_models(self.llm, first.model, avoid) if first_numbers else []
        if not models or not _time_left(deadline, AGREEMENT_MIN_SECONDS):
            return None
        timeout = AGREEMENT_MAX_SECONDS
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic() - RETRY_MARGIN_SECONDS)
        with timed(timer, "agree"):
            # The same messages as the first call, not a conversation with the first answer:
            # a second model shown that answer tends to repeat it instead of reading the table.
            return await second_opinion(self.llm.complete, messages, models, first_numbers, asked,
                                        lambda raw: _grade(raw, hits)[0], timeout)

    async def answer(self, question: str, asker: Division, target: Division, hits: List[Hit],
                     deadline: Optional[float] = None, timer: Optional[StepTimer] = None,
                     history: Sequence[Dict[str, str]] = (), refused_by: Sequence[str] = ()) -> Answer:
        """Answer from the hits.

        `deadline` is a time.monotonic() value that bounds the optional retry;
        `timer` records the llm, citations, retry and suggest steps; `history`
        is the conversation so far (see build_messages); `refused_by` are
        divisions a refusal must not suggest (see suggest_divisions).
        """
        return await self._answer(question, asker, target, hits, deadline, timer, history, self.llm.complete,
                                  refused_by)

    async def answer_stream(self, question: str, asker: Division, target: Division, hits: List[Hit], emit: Emit,
                            deadline: Optional[float] = None, timer: Optional[StepTimer] = None,
                            history: Sequence[Dict[str, str]] = (), refused_by: Sequence[str] = ()) -> Answer:
        """answer(), passing the model's text on while it is written.

        emit("delta", {"text"}) gets each new piece of text to show, and
        emit("replace", {"text": ""}) clears it when the retry starts over. The
        returned Answer is the one answer() would give: its text is graded and
        renumbered, so it replaces the streamed text once it is complete.
        """
        calls = 0

        async def call(messages: List[Dict[str, str]], models: Optional[Sequence[str]] = None) -> Completion:
            nonlocal calls
            calls += 1
            if calls > 1:
                emit("replace", {"text": ""})
            return await self._streamed(messages, models, emit)

        return await self._answer(question, asker, target, hits, deadline, timer, history, call, refused_by)

    async def _streamed(self, messages: List[Dict[str, str]], models: Optional[Sequence[str]], emit: Emit) -> Completion:
        """One streamed model call, its visible text emitted as "delta" events."""
        visible = _VisibleText()
        stream = self.llm.complete_stream(messages, models=models)
        async for piece in stream:
            text = visible.feed(piece)
            if text:
                emit("delta", {"text": text})
        rest = visible.end()
        if rest:
            emit("delta", {"text": rest})
        return Completion(stream.text, stream.model)

    async def _answer(self, question: str, asker: Division, target: Division, hits: List[Hit],
                      deadline: Optional[float], timer: Optional[StepTimer], history: Sequence[Dict[str, str]],
                      call: _Call, refused_by: Sequence[str] = ()) -> Answer:
        """The answer, with `call` asking the model (complete(), or a streamed call)."""
        if not hits:
            return Answer(refusal_text(target, []), refused=True)
        messages = build_messages(question, asker, target, hits, history)
        with timed(timer, "llm"):
            completion = await call(messages)
        first_model = completion.model
        with timed(timer, "citations"):
            text, sources = _grade(completion.text, hits)
        retried = False
        # Only a "not found" is retried: it is short, so the retry costs little
        # before the visitor sees an answer, while a written-out uncited answer is kept.
        if not text and self._worth_retrying(hits, deadline):
            retried = True
            with timed(timer, "retry"):
                second = await self._retry(messages, completion, hits, target, deadline, call)
            if second and second[2]:
                # The checks below read the passages and the conversation the retry answered from.
                completion, text, sources, messages, hits = second
            elif second:
                # Still a refusal, now from the retry's model: name that one, so the
                # page shows which two models refused instead of the first one twice.
                completion = second[0]
        asked = "\n".join([question, *(turn.get("question") or "" for turn in recent_turns(history))])
        citation_fix = None
        if text and not sources:
            if _time_left(deadline, RECHECK_MIN_SECONDS):
                with timed(timer, "recite"):
                    again = await self._recite(messages, completion, hits, deadline, call)
                # Only a cited answer that keeps every number of the first replaces it: a
                # refusal after "cite your passages" is no better than an answer the reader
                # can't check yet, and asked again the model sometimes re-read the table and
                # changed the value (Detail 3-2A, DAR-652 tuning split: N width 5 ft became 6 ft,
                # runout length 330 ft became 290 ft). Then the first answer's numbers decide.
                if again and again[2] and not unverified_numbers(text, [again[1]], asked):
                    completion, text, sources = again
                    citation_fix = "asked_again"
            n = None if sources else number_source(text, hits, asked)
            if n:
                # Cited as if the model had written the marker, so the number check reads that passage.
                completion = Completion(with_marker(text, n), completion.model)
                text, sources = _grade(completion.text, hits)
                citation_fix = "number_match"
        unverified = _unverified(completion.text, text, hits, asked) if text else []
        if unverified and _time_left(deadline, RECHECK_MIN_SECONDS):
            with timed(timer, "recheck"):
                again = await self._recheck(messages, completion, unverified, hits, asked, deadline, call)
            # The second answer replaces the first only when it is a cited answer with
            # fewer unverified numbers: a refusal or an uncited answer after "only numbers
            # in the passages" is no better than a flagged answer that cites its pages,
            # and one unsupported number swapped for another is no correction.
            if again and again[2] and len(again[3]) < len(unverified):
                completion, text, sources, unverified = again
        refused_first = [first_model] if retried and first_model != completion.model else []
        opinion = (await self._second_opinion(messages, completion, text, hits, asked, deadline, timer, refused_first)
                   if text else None)
        if opinion:
            unverified = list(dict.fromkeys([*unverified, *opinion.disagreed]))
        if not text:
            with timed(timer, "suggest"):
                # The same text the question was searched with, so a refused follow-up is matched on its topic.
                suggest = await asyncio.to_thread(self.suggest_divisions, self.search_query(question, history), target,
                                                  deadline, refused_by)
            return Answer(refusal_text(target, suggest), refused=True, model=completion.model, suggest=suggest,
                          retried=retried, first_model=first_model)
        return Answer(text, refused=False, sources=sources, model=completion.model, retried=retried,
                      first_model=first_model, uncited=not sources, unverified=unverified, citation_fix=citation_fix,
                      second_opinion=opinion)
