"""Checked answers to frequent questions, served in under a second (DAR-673).

Dr. Namian (Nov 5) asked for frequently asked questions: a question asked
often should not wait the 7.5 s median of the full pipeline. A stored answer is
served only when the new question means the same thing, because a stored answer
given to a question that is similar but different (50 mph vs 55 mph, asphalt vs
concrete) is a confident wrong answer that skips every check.

What gets stored (all must hold; `validate_entry` checks what a script can):

    1. Asked often: at least MIN_ASKED times in ASKED_WINDOW_DAYS days by at least
       MIN_ASKERS people, rewordings counted as one question. The counts come from
       the question log (DAR-676); until it exists the store stays empty.
       Dr. Namian (Nov 17): no seed list, no AI-written or hand-picked questions.
    2. One fixed answer: one division, cited, not a refusal, no "it depends".
    3. Checked by a person (Ryan or a division contact), name and date stored.

Serving (`FaqService.lookup`), only for the first question of a conversation (a
follow-up depends on the earlier turns, which a stored answer never saw):

    - only the target division's entries, and only ones whose cited documents are
      among the documents the visitor ticked;
    - the numbers and units of the two questions are the same (numbers.py's
      normalization: "55 mph" = "55 miles per hour", "2 ft" = "2 feet");
    - the same contrast words (CONTRAST_WORDS: negations, minimum/maximum,
      outside, left/right, metric units, ...): the embedding hardly moves for them
      ("in" vs "outside the right of way" scored 0.99, "with" vs "without prior
      rights" 0.988), so they are compared as words, like the numbers;
    - question-to-question cosine similarity at or above FAQ_THRESHOLD, both
      embedded as plain text (no BGE query instruction: two questions are
      compared with each other, not a question with a passage). The threshold is
      set from the test pairs in evaluation/faq/ (RESULTS.md), never by feel;
    - the entry is still current: every cited page's text in the loaded index has
      the fingerprint stored with the entry (else the entry is pulled at once and
      queued for re-checking), and the division's documents are the ones the entry
      was checked against (else it waits for `scripts/faq.py check` to re-run it).

The store is the Upstash Redis database already on the Vercel project
(spend.py's), one hash per division under faq:<namespace>:. Preview and
production share that database, so the namespace is VERCEL_ENV: a preview built
from a rebuilt index can never pull production's entries. When the store can't be
reached the question simply goes through the full pipeline.
"""

import asyncio
import hashlib
import json
import logging
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import (Any, Awaitable, Callable, Dict, FrozenSet, Iterable, List, Mapping, NamedTuple, Optional,
                    Sequence, Set, Tuple)

import numpy as np

from .divisions import BY_ID, DIVISIONS
from .index_file import IndexFile, search_text
from .numbers import numbers_with_units
from .spend import RedisStore, StoreError

log = logging.getLogger(__name__)

# Starts at 0.95, as semantic-cache guidance advises (Portkey), and stays there (evaluation/faq/RESULTS.md):
# on the tuning pairs 0.95 is the lowest threshold that served none of the 30 similar-but-different
# questions (24/30 rewordings), and on the held-out pairs 0.948 would already have served "quality
# level A" the answer stored for "level B" (similarity 0.949). Lower it only after a backtest on
# logged question pairs (DAR-676); recall grows instead through checked `aliases`.
DEFAULT_THRESHOLD = 0.95
MIN_ASKED = 5
MIN_ASKERS = 3
ASKED_WINDOW_DAYS = 30
KEY_PREFIX = "faq"
# A lookup that can't reach the store in this long gives up: the full pipeline answers instead.
LOOKUP_TIMEOUT_SECONDS = 1.0
# "it depends" answers are not one fixed answer (criterion 2).
_DEPENDS = re.compile(r"\b(?:it|that|this|which|answer)\s+depends\b|\bdepends\s+on\b", re.IGNORECASE)
_MARKER = re.compile(r"\s*\[\d+(?:\s*[,\-–]\s*\d+)*\]")

# Words that flip a question's answer while barely moving its embedding, by class: a question
# and a stored one must name the same classes. Written as general word classes (negation and
# opposites) after the tuning pairs showed the embedding missing them, and frozen before the
# held-out pairs (written by someone who never saw this list) were first run.
CONTRAST_WORDS: Dict[str, Tuple[str, ...]] = {
    "not": ("not", "no", "non", "without", "except", "excluding", "never", "neither", "nor", "cannot"),
    "min": ("minimum", "min", "minimal", "least", "shortest", "smallest", "lowest", "fewest", "narrowest",
            "closest", "nearest", "at_least"),
    "max": ("maximum", "max", "most", "longest", "largest", "biggest", "highest", "greatest", "widest",
            "furthest", "farthest", "at_most"),
    "outside": ("outside", "beyond", "exterior", "outer"),
    "left": ("left",),
    "right": ("right",),
    "over": ("over", "above"),
    "under": ("under", "below", "beneath", "underneath", "underground"),
    "before": ("before", "preceding"),
    "after": ("after",),
    "upstream": ("upstream",),
    "downstream": ("downstream",),
    "day": ("daytime", "daylight"),
    "night": ("night", "nighttime", "nights", "overnight"),
    "rural": ("rural",),
    "urban": ("urban", "urbanized"),
    "temporary": ("temporary", "temp"),
    "permanent": ("permanent",),
    "new": ("new", "proposed"),
    "existing": ("existing",),
    # NCDOT's manuals are in US customary units: a question in metric asks for a conversion.
    "metric": ("metric", "meter", "meters", "metre", "metres", "km", "kilometer", "kilometers", "kilometre",
               "kilometres", "kph", "cm", "centimeter", "centimeters", "mm", "millimeter", "millimeters",
               "kg", "kilogram", "kilograms"),
}
_CLASS_OF = {word: name for name, words in CONTRAST_WORDS.items() for word in words}
# Phrases first, so "no more than" is a maximum and not a negation, and "right of way" is no side.
_PHRASES = (
    (re.compile(r"\b(?:no|not)\s+(?:more|greater|higher|longer|larger)\s+than\b|\bat\s+most\b|\bup\s+to\b"), " at_most "),
    (re.compile(r"\b(?:no|not)\s+(?:less|fewer|lower|shorter|smaller)\s+than\b|\bat\s+least\b"), " at_least "),
    (re.compile(r"\brights?[\s-]+of[\s-]+ways?\b"), " row "),
    (re.compile(r"n't\b"), " not"),
)
_TOKEN = re.compile(r"[a-z]+")


def contrast_classes(text: str) -> FrozenSet[str]:
    """The CONTRAST_WORDS classes the text names."""
    out = (text or "").lower().replace("’", "'")
    for pattern, replacement in _PHRASES:
        out = pattern.sub(replacement, out)
    out = out.replace("at_most", " atmost ").replace("at_least", " atleast ")
    classes = set()
    for token in _TOKEN.findall(out):
        token = {"atmost": "at_most", "atleast": "at_least"}.get(token, token)
        if token in _CLASS_OF:
            classes.add(_CLASS_OF[token])
    return frozenset(classes)


def number_key(text: str) -> Tuple[Tuple[float, Optional[str]], ...]:
    """The text's numbers with their units, sorted: two questions must have the same ones."""
    return tuple(sorted(((round(value, 9), unit) for value, unit, _ in numbers_with_units(text)),
                        key=lambda item: (item[0], item[1] or "")))


def question_key(text: str) -> Tuple[Tuple[Tuple[float, Optional[str]], ...], FrozenSet[str]]:
    """What must be equal before similarity counts at all: numbers with units, and contrast classes."""
    return number_key(text), contrast_classes(text)


def same_text(a: str, b: str) -> bool:
    """The same question, ignoring case, spacing and the question mark."""
    def plain(text: str) -> str:
        return " ".join(re.sub(r"[?.!\s]+$", "", (text or "").lower()).split())
    return plain(a) == plain(b)


def answer_numbers(text: str) -> Tuple[Tuple[float, Optional[str]], ...]:
    """The numbers an answer states, without its [n] citation markers."""
    return number_key(_MARKER.sub("", text or ""))


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

@dataclass
class Entry:
    """One checked answer. `sources` are the answer's sources as /api/ask returned them."""
    id: str
    division: str
    question: str
    answer: str
    sources: List[Dict[str, Any]]
    checked_by: str
    checked_on: str  # YYYY-MM-DD, the person's check; the reply shows it
    asked: Dict[str, Any]  # {"times", "askers", "days"} from the question log
    pages: List[Dict[str, Any]] = field(default_factory=list)  # [{"file", "page", "fingerprint"}], every cited page
    documents: List[str] = field(default_factory=list)  # the division's documents the answer was checked against
    added_on: Optional[str] = None
    rechecked_on: Optional[str] = None  # the last automatic re-run that gave the same answer
    # Other phrasings a person confirmed ask the same thing (the question log groups rewordings as one
    # question, criterion 1). Matched like `question`: the bge-small similarity of a looser paraphrase
    # ("who has to prepare the TMP?") is far below the threshold, so this is how such askers get served.
    aliases: List[str] = field(default_factory=list)

    @property
    def phrasings(self) -> List[str]:
        return [self.question] + [a for a in self.aliases if a and a != self.question]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "Entry":
        data = json.loads(raw)
        known = {f for f in cls.__dataclass_fields__}  # a field added later doesn't break reading older entries
        return cls(**{k: v for k, v in data.items() if k in known})


def file_for_source(division: str, source: Mapping[str, Any]) -> Optional[str]:
    """The document file a payload source points to (its url without #page, else its title)."""
    url = str(source.get("url") or "").split("#", 1)[0]
    title = source.get("title")
    for document in BY_ID[division].documents:
        if (url and document.url == url) or (not url and title and document.title == title):
            return document.file
    return None


def cited_pages(division: str, sources: Iterable[Mapping[str, Any]]) -> List[Tuple[str, int]]:
    """Every (file, page) the sources cite, page through page_end, in order."""
    pages: List[Tuple[str, int]] = []
    for source in sources:
        file, first = file_for_source(division, source), source.get("page")
        if file is None or not isinstance(first, int):
            raise ValueError(f"source {source.get('title')!r} p.{first} is not a page of a {division} document")
        last = source.get("page_end") if isinstance(source.get("page_end"), int) else first
        for page in range(first, max(first, last) + 1):
            if (file, page) not in pages:
                pages.append((file, page))
    return pages


class PageText:
    """Fingerprints of the indexed text of pages, and each division's documents, from one index."""

    def __init__(self, index: IndexFile):
        self.index = index
        self._by_page: Optional[Dict[Tuple[str, str, int], List[int]]] = None
        self._documents: Dict[str, FrozenSet[str]] = {}

    def _pages(self) -> Dict[Tuple[str, str, int], List[int]]:
        if self._by_page is None:
            by_page: Dict[Tuple[str, str, int], List[int]] = defaultdict(list)
            for i, chunk in enumerate(self.index.chunks):
                first = chunk.get("page")
                if not isinstance(first, int):
                    continue
                last = chunk.get("page_end") if isinstance(chunk.get("page_end"), int) else first
                for page in range(first, max(first, last) + 1):
                    by_page[(chunk.get("division") or "", chunk.get("source") or "", page)].append(i)
            self._by_page = dict(by_page)
        return self._by_page

    def fingerprint(self, division: str, file: str, page: int) -> Optional[str]:
        """A hash of every indexed text (search_text) on the page, in index order; None when the page is gone."""
        rows = self._pages().get((division, file, page))
        if not rows:
            return None
        digest = hashlib.sha256()
        for i in rows:
            digest.update(search_text(self.index.chunks[i]).encode("utf-8"))
            digest.update(b"\x1e")
        return digest.hexdigest()[:20]

    def documents(self, division: str) -> FrozenSet[str]:
        """The division's searchable documents in the index (superseded editions left out)."""
        if division not in self._documents:
            # Documents a newer edition replaced (DAR-674's register, when the index has one) are never searched.
            superseded = getattr(self.index, "superseded", None) or ()
            self._documents[division] = frozenset(
                c.get("source") for c in self.index.chunks
                if c.get("division") == division and c.get("source") and c.get("source") not in superseded)
        return self._documents[division]

    def stale_pages(self, entry: Entry) -> List[str]:
        """The entry's cited pages whose text changed or is gone, as "file p.N (changed|removed)"."""
        stale = []
        for page in entry.pages:
            now = self.fingerprint(entry.division, page["file"], page["page"])
            if now != page.get("fingerprint"):
                stale.append(f"{page['file']} p.{page['page']} ({'removed' if now is None else 'changed'})")
        return stale

    def documents_changed(self, entry: Entry) -> Tuple[List[str], List[str]]:
        """(added, removed) documents of the entry's division since it was checked."""
        now, then = self.documents(entry.division), set(entry.documents)
        return sorted(now - then), sorted(then - now)

    def stamp(self, entry: Entry) -> Entry:
        """The entry with its cited pages' fingerprints and the division's documents taken from this index."""
        pages = []
        for file, page in cited_pages(entry.division, entry.sources):
            fingerprint = self.fingerprint(entry.division, file, page)
            if fingerprint is None:
                raise ValueError(f"{file} p.{page} is not in this index")
            pages.append({"file": file, "page": page, "fingerprint": fingerprint})
        entry.pages = pages
        entry.documents = sorted(self.documents(entry.division))
        return entry


def validate_entry(entry: Entry) -> List[str]:
    """Why the entry can't be stored (empty when it can): the criteria a script can check."""
    problems = []
    if entry.division not in BY_ID:
        problems.append(f"unknown division {entry.division!r}")
        return problems
    asked = entry.asked or {}
    times, askers, days = asked.get("times"), asked.get("askers"), asked.get("days")
    if not (isinstance(times, int) and times >= MIN_ASKED and isinstance(askers, int) and askers >= MIN_ASKERS
            and isinstance(days, int) and 0 < days <= ASKED_WINDOW_DAYS):
        problems.append(f"asked must show at least {MIN_ASKED} times by at least {MIN_ASKERS} people within "
                        f"{ASKED_WINDOW_DAYS} days (from the question log), got {asked}")
    if not (entry.checked_by or "").strip():
        problems.append("checked_by is empty: a person must check the answer and its cited pages")
    try:
        date.fromisoformat(entry.checked_on or "")
    except ValueError:
        problems.append(f"checked_on must be a date, YYYY-MM-DD, got {entry.checked_on!r}")
    if not (entry.question or "").strip() or not (entry.answer or "").strip():
        problems.append("question and answer must both be set")
    if not entry.sources:
        problems.append("the answer cites no source")
    if any(s.get("division") not in (None, entry.division) for s in entry.sources):
        problems.append("every source must be from the entry's division")
    if _DEPENDS.search(entry.answer or ""):
        problems.append("the answer says it depends: not one fixed answer")
    if answer_refuses(entry.answer):
        problems.append("the answer is a refusal")
    try:
        cited_pages(entry.division, entry.sources)
    except ValueError as exc:
        problems.append(str(exc))
    return problems


def answer_refuses(text: str) -> bool:
    return "NOT_IN_DOCUMENTS" in (text or "") or (text or "").lstrip().startswith("I couldn't find")


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

class FaqStore:
    """Entries per division and the re-checking queue, in Redis (or this process's memory).

        faq:<namespace>:<division>   hash  entry id -> Entry JSON
        faq:<namespace>:queue        hash  entry id -> {"entry", "reason", "pulled_on", "new_answer"?}
    """

    def __init__(self, redis: Optional[RedisStore] = None, namespace: str = "local"):
        self.redis = redis
        self.namespace = namespace
        self._memory: Dict[str, Dict[str, str]] = defaultdict(dict)

    @property
    def shared(self) -> bool:
        return self.redis is not None

    def key(self, name: str) -> str:
        return f"{KEY_PREFIX}:{self.namespace}:{name}"

    async def _run(self, *commands: list) -> list:
        if self.redis is not None:
            return await self.redis.pipeline(*commands)
        results = []
        for command in commands:
            op, key, *args = command
            table = self._memory[key]
            if op == "HGETALL":
                results.append([x for pair in table.items() for x in pair])
            elif op == "HSET":
                table[args[0]] = args[1]
                results.append(1)
            elif op == "HDEL":
                results.append(1 if table.pop(args[0], None) is not None else 0)
            else:
                raise StoreError(f"memory store has no {op}")
        return results

    @staticmethod
    def _pairs(flat: Optional[list]) -> Dict[str, str]:
        flat = flat or []
        return {flat[i]: flat[i + 1] for i in range(0, len(flat) - 1, 2)}

    async def entries(self, division: str) -> List[Entry]:
        (flat,) = await self._run(["HGETALL", self.key(division)])
        entries = []
        for entry_id, raw in self._pairs(flat).items():
            try:
                entries.append(Entry.from_json(raw))
            except (ValueError, TypeError) as exc:
                log.warning("faq entry %s in %s is unreadable (%s); skipped", entry_id, division, exc)
        return entries

    async def all_entries(self) -> List[Entry]:
        replies = await self._run(*(["HGETALL", self.key(d.id)] for d in DIVISIONS))
        entries = []
        for flat in replies:
            entries.extend(Entry.from_json(raw) for raw in self._pairs(flat).values())
        return entries

    async def put(self, entry: Entry) -> None:
        await self._run(["HSET", self.key(entry.division), entry.id, entry.to_json()])

    async def pull(self, entry: Entry, reason: str, new_answer: Optional[Dict[str, Any]] = None,
                   today: Optional[str] = None) -> None:
        """Take the entry out of service at once and queue it for a person to re-check."""
        queued = {"entry": json.loads(entry.to_json()), "reason": reason,
                  "pulled_on": today or date.today().isoformat()}
        if new_answer is not None:
            queued["new_answer"] = new_answer
        await self._run(["HDEL", self.key(entry.division), entry.id],
                        ["HSET", self.key("queue"), entry.id, json.dumps(queued, ensure_ascii=False)])
        log.warning("faq entry %s (%s) pulled: %s", entry.id, entry.division, reason)

    async def queue(self) -> List[Dict[str, Any]]:
        (flat,) = await self._run(["HGETALL", self.key("queue")])
        return [json.loads(raw) for raw in self._pairs(flat).values()]

    async def remove(self, entry_id: str) -> int:
        """Delete an entry and its queue item wherever they are; returns how many were removed."""
        replies = await self._run(*(["HDEL", self.key(d.id), entry_id] for d in DIVISIONS),
                                  ["HDEL", self.key("queue"), entry_id])
        return sum(int(r or 0) for r in replies)


def namespace_from_env(env: Mapping[str, str]) -> str:
    """FAQ_NAMESPACE, else Vercel's environment (production, preview), else "local"."""
    return (env.get("FAQ_NAMESPACE", "").strip() or env.get("VERCEL_ENV", "").strip() or "local").lower()


def store_from_env(env: Mapping[str, str], timeout: float = LOOKUP_TIMEOUT_SECONDS) -> FaqStore:
    """The Upstash store spend.py uses (same variables), namespaced; this process's memory without one."""
    for url_name, token_name in (("KV_REST_API_URL", "KV_REST_API_TOKEN"),
                                 ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN")):
        url, token = env.get(url_name, "").strip(), env.get(token_name, "").strip()
        if url and token:
            return FaqStore(RedisStore(url, token, timeout=timeout), namespace_from_env(env))
    return FaqStore(None, namespace_from_env(env))


# ---------------------------------------------------------------------------
# Serving
# ---------------------------------------------------------------------------

class Match(NamedTuple):
    entry: Entry
    similarity: float


Embed = Callable[[Sequence[str]], np.ndarray]


def best_match(question: str, vector: Optional[np.ndarray],
               candidates: Sequence[Tuple[Entry, str, Optional[np.ndarray]]], threshold: float) -> Optional[Match]:
    """The entry whose phrasing is most similar among those passing the number and contrast-word rules and the threshold.

    `candidates` are (entry, one of its phrasings, that phrasing's embedding). The
    same text (same_text) is a match with similarity 1. `vector` may be None when
    only same-text matches are possible (no embedder loaded yet).
    """
    key = question_key(question)
    best: Optional[Match] = None
    for entry, phrasing, phrasing_vector in candidates:
        if question_key(phrasing) != key:
            continue
        if same_text(question, phrasing):
            similarity = 1.0
        elif vector is None or phrasing_vector is None:
            continue
        else:
            similarity = float(np.dot(vector, phrasing_vector))
        if similarity >= threshold and (best is None or similarity > best.similarity):
            best = Match(entry, similarity)
    return best


class FaqService:
    """Looks up a checked answer for a question; one per server instance."""

    def __init__(self, store: FaqStore, pages: PageText, threshold: float = DEFAULT_THRESHOLD):
        self.store = store
        self.pages = pages
        self.threshold = threshold
        self._vectors: Dict[str, np.ndarray] = {}  # stored question -> its embedding, kept for this instance
        self._pending: Set[asyncio.Task] = set()

    def vectors(self, questions: Sequence[str], embed: Embed) -> List[np.ndarray]:
        """The questions' embeddings, computing only the ones this instance hasn't seen."""
        missing = [q for q in dict.fromkeys(questions) if q not in self._vectors]
        if missing:
            for question, vector in zip(missing, embed(missing)):
                self._vectors[question] = np.asarray(vector, dtype=np.float32)
        return [self._vectors[q] for q in questions]

    def _servable(self, entry: Entry, documents: Optional[Sequence[str]]) -> bool:
        files = {page["file"] for page in entry.pages}
        if not files:
            return False
        # Only documents the visitor ticked may be cited (None: all of the division's).
        return documents is None or files <= set(documents)

    async def lookup(self, question: str, division: str, documents: Optional[Sequence[str]],
                     embed: Optional[Embed]) -> Optional[Match]:
        """The checked answer to serve, or None for the full pipeline.

        `embed` None (models not loaded on this instance yet) allows same-text matches only.
        """
        try:
            entries = await self.store.entries(division)
        except StoreError as exc:
            log.warning("faq store unreachable (%s); answering in full", exc)
            return None
        candidates = [e for e in entries if e.division == division and self._servable(e, documents)]
        if not candidates:
            return None
        key = question_key(question)
        phrasings = [(e, p) for e in candidates for p in e.phrasings]
        vector, phrasing_vectors = None, [None] * len(phrasings)
        # Embedding is only worth it when some phrasing could pass the word rules.
        if embed is not None and any(question_key(p) == key for _, p in phrasings):
            vectors = await asyncio.to_thread(self.vectors, [question] + [p for _, p in phrasings], embed)
            vector, phrasing_vectors = vectors[0], vectors[1:]
        match = best_match(question, vector, [(e, p, v) for (e, p), v in zip(phrasings, phrasing_vectors)],
                           self.threshold)
        if match is None:
            return None
        stale = self.pages.stale_pages(match.entry)
        if stale:
            # The deployed index's text of a cited page differs from the checked one: pull it now.
            self._soon(self.store.pull(match.entry, "cited page changed in the index: " + "; ".join(stale)))
            return None
        added, removed = self.pages.documents_changed(match.entry)
        if added or removed:
            # The division's documents changed since the check: scripts/faq.py check re-runs it first.
            log.info("faq entry %s not served: documents changed since its check (added %s, removed %s)",
                     match.entry.id, added, removed)
            return None
        return match

    def _soon(self, work: Awaitable[None]) -> None:
        async def run() -> None:
            try:
                await work
            except StoreError as exc:
                log.warning("faq entry could not be pulled (%s); it is skipped until it is", exc)
        task = asyncio.get_running_loop().create_task(run())
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)


def served_payload(match: Match) -> Dict[str, Any]:
    """The answer fields of /api/ask's reply for a checked answer (index.py adds the rest)."""
    entry = match.entry
    return {
        "answer": entry.answer,
        "refused": False,
        "uncited": False,
        "unverified": [],
        "sources": [dict(s) for s in entry.sources],
        "model": None,
        "first_model": None,
        "backup_model": False,
        "retried": False,
        "citation_fix": None,
        "second_opinion": None,
        "suggest": [],
        "checked_answer": {"id": entry.id, "checked_on": entry.checked_on, "similarity": round(match.similarity, 4)},
    }


# ---------------------------------------------------------------------------
# Keeping entries current (scripts/faq.py check)
# ---------------------------------------------------------------------------

Rerun = Callable[[Entry], Awaitable[Dict[str, Any]]]


def same_answer(entry: Entry, reply: Mapping[str, Any]) -> Tuple[bool, str]:
    """Whether a fresh /api/ask reply gives the entry's answer: not refused, the same cited pages and numbers.

    The wording of a model's answer varies from run to run, so the text itself is
    not compared: what a reader acts on is the value and the page it comes from.
    """
    if reply.get("refused") or reply.get("error"):
        return False, "the full pipeline now refuses" if reply.get("refused") else f"error: {reply.get('error')}"
    if reply.get("uncited") or not reply.get("sources"):
        return False, "the full pipeline's answer cites no page"
    try:
        then = set(cited_pages(entry.division, entry.sources))
        now = set(cited_pages(entry.division, reply.get("sources") or []))
    except ValueError as exc:
        return False, str(exc)
    if then != now:
        return False, (f"cited pages changed: {sorted(then)} -> {sorted(now)}")
    if answer_numbers(entry.answer) != answer_numbers(reply.get("answer") or ""):
        return False, (f"numbers changed: {answer_numbers(entry.answer)} -> {answer_numbers(reply.get('answer') or '')}")
    return True, "same cited pages and numbers"


@dataclass
class CheckReport:
    kept: List[str] = field(default_factory=list)  # unchanged, or re-run with the same answer
    rechecked: List[str] = field(default_factory=list)  # re-run after documents changed, same answer
    pulled: List[Tuple[str, str]] = field(default_factory=list)  # (id, reason)
    needs_rerun: List[str] = field(default_factory=list)  # documents changed, no site given to re-run on


async def check_entries(store: FaqStore, pages: PageText, rerun: Optional[Rerun] = None,
                        today: Optional[str] = None) -> CheckReport:
    """After an index rebuild: pull entries whose cited pages changed; re-run the ones whose division's documents
    changed (added or removed) through the full pipeline, keeping the same answer and pulling a different one."""
    today = today or date.today().isoformat()
    report = CheckReport()
    for entry in await store.all_entries():
        stale = pages.stale_pages(entry)
        if stale:
            reason = "cited page changed in the index: " + "; ".join(stale)
            await store.pull(entry, reason, today=today)
            report.pulled.append((entry.id, reason))
            continue
        added, removed = pages.documents_changed(entry)
        if not (added or removed):
            report.kept.append(entry.id)
            continue
        if rerun is None:
            report.needs_rerun.append(entry.id)
            continue
        reply = await rerun(entry)
        same, why = same_answer(entry, reply)
        if same:
            entry.rechecked_on = today
            entry.documents = sorted(pages.documents(entry.division))
            await store.put(entry)
            report.rechecked.append(entry.id)
        else:
            changes = ", ".join(x for x in (f"added {added}" if added else "", f"removed {removed}" if removed else "") if x)
            reason = f"documents changed ({changes}) and the full pipeline's answer differs: {why}"
            await store.pull(entry, reason, new_answer=dict(reply), today=today)
            report.pulled.append((entry.id, reason))
    return report
