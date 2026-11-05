"""A precomputed search index as two plain files in one directory.

    chunks.json   {"model": ..., "dim": ..., "chunks": [{"text", "source", "page", "section", "division"}, ...]}
    vectors.npy   float16 array, one unit-length row per chunk, in the same order
    bm25.npz      the keyword index (keyword.py), when the build made one

A chunk may also have a `context` line (the document, page and the page's
figure/table captions, see prototype.ingest.context_line). It is embedded,
keyword-searched and reranked with the text (search_text) and shown to the
model, but the sources panel shows only `text`, the page's own words. The
keyword index also has a caption/ID field per chunk (field_text): captions,
table and figure numbers, document title and section.

`division` is the id of the division (divisions.py) whose documents the chunk
came from. Search is a dot product (cosine similarity, as rows and queries are
unit length); a division filter restricts it to that division's rows before
ranking, so another division's chunk can never be returned. A `sources` filter
(document file names) narrows it further to the documents the visitor ticked.
Only numpy is needed to load and search it.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .divisions import document_for
from .keyword import KEYWORD_FILE, VERSION, KeywordIndex
from .query import ID_PATTERN, id_name

CHUNKS_FILE = "chunks.json"
VECTORS_FILE = "vectors.npy"

log = logging.getLogger(__name__)

# A caption: a line that starts "Figure 5 ..." or "Table 3-2 ...", as prototype.ingest.captions finds
# them for the context line; longer lines are prose that mentions the figure, not its caption.
_CAPTION_LINE = re.compile(r"^[#*\s]*((?:Figure|FIGURE|Table|TABLE|Exhibit)\s+[0-9A-Z][\w.\-]*\b.*?)[*\s]*$", re.MULTILINE)
_CAPTION_START = re.compile(r"^(?:Figure|FIGURE|Table|TABLE|Exhibit)\b")
_MAX_CAPTION_CHARS = 150
# Every table, figure, exhibit, section, sheet and standard the text names ("Table 3-2", "Fig. 2-1",
# "Section 4.2") is found with query.ID_PATTERN and written with query.id_name, so "Fig. 2-1" here and
# "figure 2-1" in a question become the same "Figure 2-1". Document codes: NCDOT's "04-20340" and
# leading-zero numbers such as "04091", but not the decimals of "0.0200" (a slope, not a code).
_DOC_CODE = re.compile(r"\b[0-9]{2}-[0-9]{5}\b|(?<![0-9.])0[0-9]{3,5}\b")
_PAGE_SEGMENT = re.compile(r"^(?:printed\s+)?p\.\s*\S+$")


def search_text(chunk: Dict[str, Any]) -> str:
    """What the search reads of a chunk: its context line (when it has one), then its text."""
    context = chunk.get("context")
    return f"{context}\n{chunk['text']}" if context else chunk["text"]


def context_parts(context: str) -> Dict[str, Any]:
    """The context line's document title and captions: "[title · p.N · caption; caption]".

    Segments are read by what they look like, not by position, so a line with a
    "printed p.X" segment after "p.N" (another build) parses the same: the first
    segment is the title, page segments are skipped, and a caption is a segment
    (or a "; "-separated part of one) starting Figure/Table/Exhibit.
    """
    segments = [s.strip() for s in context.strip().strip("[]").split(" · ")]
    captions = [part.strip() for segment in segments[1:] if not _PAGE_SEGMENT.match(segment)
                for part in segment.split("; ") if _CAPTION_START.match(part.strip())]
    return {"title": segments[0], "captions": captions}


def field_text(chunk: Dict[str, Any]) -> str:
    """The chunk's caption/ID field for the keyword index (keyword.py): what names its page, not what it says.

    The page's captions (from the context line, and caption lines in the text),
    every table, figure, section, sheet or standard number the text names,
    document codes, the document's title and file name, and the chunk's section.
    A chunk whose page is captioned "Table 3-2" is then found by that name
    before the many chunks that only hold a "3" and a "2" (DAR-657).
    """
    lines: List[str] = []
    context = chunk.get("context")
    if context:
        lines.extend(context_parts(context)["captions"])
    text = chunk.get("text", "")
    lines.extend(c for c in (" ".join(m.group(1).replace("**", "").split()) for m in _CAPTION_LINE.finditer(text))
                 if len(c) <= _MAX_CAPTION_CHARS)
    # The IDs of the page's own captions count once more (appended after the de-duplication below)
    # than an ID the text only mentions: a page that says "see Table 3-2" has a shorter field than the
    # page captioned "Table 3-2", and BM25's length normalisation would otherwise rank it above the table.
    captioned = [id_name(m) for line in lines for m in ID_PATTERN.finditer(line)]
    lines.extend(id_name(m) for m in ID_PATTERN.finditer(text))
    lines.extend(_DOC_CODE.findall(text))
    source = chunk.get("source") or ""
    document = document_for(source) if source else None
    if document is not None:
        lines.append(document.title)
    elif context:
        lines.append(context_parts(context)["title"])
    if source:
        lines.append(Path(source).stem)
    if chunk.get("section"):
        lines.append(chunk["section"])
    return "\n".join(list(dict.fromkeys(line for line in lines if line)) + captioned)


@dataclass(frozen=True)
class Hit:
    score: float
    chunk: Dict[str, Any]


class IndexFile:
    def __init__(self, model: str, chunks: List[Dict[str, Any]], vectors: np.ndarray,
                 keyword: Optional[KeywordIndex] = None):
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        self.model = model
        self.chunks = chunks
        self.vectors = vectors
        self.keyword = keyword
        self._rows_cache: Dict[Optional[str], np.ndarray] = {}
        self._position = {id(chunk): i for i, chunk in enumerate(chunks)}

    @classmethod
    def load(cls, directory: "str | Path") -> "IndexFile":
        directory = Path(directory)
        meta = json.loads((directory / CHUNKS_FILE).read_text(encoding="utf-8"))
        vectors = np.load(directory / VECTORS_FILE).astype(np.float32)
        if vectors.shape[1] != meta["dim"]:
            raise ValueError(f"vectors have {vectors.shape[1]} dimensions, chunks.json says {meta['dim']}")
        keyword = KeywordIndex.load(directory, len(meta["chunks"]))
        index = cls(meta["model"], meta["chunks"], vectors, keyword)
        if keyword is not None and keyword.version < VERSION:
            # A bm25.npz from before the caption/ID field (DAR-651's version 1). Its body was tokenized the
            # old way too ("12 feet" not folded to "ft", "3-2" split in two), so rebuild all of it from the
            # same chunks rather than mix vocabularies. That costs seconds on a cold start: ship a rebuilt
            # file (scripts/rebuild_keyword_index.py); this only keeps an old one answering correctly.
            index.with_keyword_index()
            log.warning("%s is version %d; rebuilt the keyword index from the chunks at load time",
                        KEYWORD_FILE, keyword.version)
        return index

    def save(self, directory: "str | Path") -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        meta = {"model": self.model, "dim": int(self.vectors.shape[1]), "chunks": self.chunks}
        (directory / CHUNKS_FILE).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        np.save(directory / VECTORS_FILE, self.vectors.astype(np.float16))
        if self.keyword is not None:
            self.keyword.save(directory)
        elif (directory / KEYWORD_FILE).exists():
            (directory / KEYWORD_FILE).unlink()  # an earlier build's, for other chunks

    def with_keyword_index(self) -> "IndexFile":
        """This index with a keyword index built from its chunks (prototype.ingest calls it before saving)."""
        self.keyword = KeywordIndex.build([search_text(c) for c in self.chunks], [c.get("division") for c in self.chunks],
                                          [field_text(c) for c in self.chunks])
        return self

    def divisions(self) -> List[str]:
        return sorted({c.get("division") for c in self.chunks if c.get("division")})

    def _rows(self, division: Optional[str], sources: Optional[Sequence[str]] = None) -> np.ndarray:
        """Row numbers of `division`'s chunks (every division when None), only from `sources` when given.

        Only whole divisions are cached. The visitor picks the `sources` subset, and
        with 20 documents a division (DAR-621) there are about a million subsets, so
        caching each would grow without bound on a warm instance; filtering a cached
        division's rows takes about a millisecond.
        """
        if division not in self._rows_cache:
            rows = [i for i, c in enumerate(self.chunks) if division is None or c.get("division") == division]
            self._rows_cache[division] = np.array(rows, dtype=int)
        rows = self._rows_cache[division]
        if sources is None:
            return rows
        wanted = set(sources)
        return np.array([i for i in rows if self.chunks[i].get("source") in wanted], dtype=int)

    def count(self, division: Optional[str] = None, sources: Optional[Sequence[str]] = None) -> int:
        """How many chunks a search with the same filters would look through."""
        return len(self._rows(division, sources))

    def position(self, chunk: Dict[str, Any]) -> int:
        """Where the chunk sits in the index: documents in order, each in reading order."""
        return self._position.get(id(chunk), len(self.chunks))

    def following(self, chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The chunk after this one in the same document (chunks are saved in reading order)."""
        i = self._position.get(id(chunk))
        if i is None or i + 1 >= len(self.chunks):
            return None
        after = self.chunks[i + 1]
        return after if after.get("source") == chunk.get("source") else None

    def search(self, query_vector: Sequence[float], k: int = 3, division: Optional[str] = None,
               sources: Optional[Sequence[str]] = None) -> List[Hit]:
        """Top k chunks by cosine similarity; only `division`'s chunks (and `sources`' documents) when given."""
        rows = self._rows(division, sources)
        if not len(rows):
            return []
        scores = self.vectors[rows] @ np.asarray(query_vector, dtype=np.float32)
        top = np.argsort(-scores)[:k]
        return [Hit(float(scores[i]), self.chunks[rows[i]]) for i in top]

    def keyword_search(self, query: str, k: int = 3, division: Optional[str] = None,
                       sources: Optional[Sequence[str]] = None, field_boost: float = 0.0,
                       ids: Sequence[str] = (), id_boost: float = 1.0) -> List[Hit]:
        """Top k chunks by BM25 score, with the same filters as `search`; [] when the index has no keyword index.

        `field_boost` adds that many times the caption/ID field's score to the
        body's, and the identifiers in `ids` (query.parse) count `id_boost`
        times in the field (keyword.KeywordIndex.scores).
        """
        if self.keyword is None:
            return []
        rows = self._rows(division, sources)
        return [Hit(score, self.chunks[i]) for i, score in self.keyword.top(query, rows, k, field_boost, ids, id_boost)]
