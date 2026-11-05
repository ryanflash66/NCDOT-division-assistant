"""Keyword (BM25) search over the index's chunks, per division.

The vector search misses passages whose match is a number, a code or a rare
term the embedding blurs: a table cell such as "42.89", a drawing number, a
section "3.6.4.1". BM25 finds those by the words themselves. Its index is built
offline with the vector index (prototype.ingest) and saved next to it:

    bm25.npz   version (2); terms (sorted vocabulary), starts (offsets into the
               postings, one per term plus the end), rows (chunk numbers) and
               weights (the BM25 weight of the term in that chunk); and the
               same four arrays with a field_ prefix for the caption/ID field

Each weight already holds the term's IDF and the chunk's length normalisation,
computed over the chunk's own division (k1 = 1.2, b = 0.75): a division is
searched on its own, so a term common in another division's manuals does not
make it rarer here. A query's score for a chunk is the sum of its terms'
weights. Like the vector search, only the asked division's rows (and the
ticked documents) are ranked, so another division's chunk is never returned.
Only numpy is needed.

Two fields (DAR-657). The body is the chunk's search text (context line and
text). The caption/ID field (index_file.field_text) is short: the page's
figure and table captions, every "Table 3-2", "Figure 5" or "Section 4.2" the
chunk names, the document's title and file name and the chunk's section. A
question that names a table or a figure then finds the chunk captioned with it
rather than any chunk that happens to hold the same digits: the score is
body + boost * field (BM25F-style, one ranking), and an ID the question names
explicitly counts `id_boost` times in the field query. A boost is never a
filter: a chunk without the ID still ranks by its body.
"""

import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

KEYWORD_FILE = "bm25.npz"
VERSION = 2
K1 = 1.2
B = 0.75
# How much the caption/ID field counts next to the body, and how much more an identifier the
# question names ("Table 3-2", "04091") counts in that field. Measured on the 15 image/table and
# 83 known-page questions (docs/keyword-field.md): field 1.5 keeps every hit the body-only search
# had (77/83, 14/15) and lifts MRR 0.756 -> 0.764; at 2 the known-page T25 drops out of the top 5,
# at 3 T17 and U17 too, as the field's title and section words start outweighing the body. No dev
# question names a table, so the ID boost (1, 2 and 4 scored the same) is set by the unit tests.
DEFAULT_FIELD_BOOST = 1.5
DEFAULT_ID_BOOST = 2.0

# One word or number, with its decimals or section dots ("42.89", "3.6.4.1", "6h").
_ATOM = r"[a-z0-9]+(?:\.[0-9]+)*"
# A fraction ("1/2"), or atoms joined by hyphens ("6h-3", "04-20340", "right-of-way").
_TOKEN = re.compile(rf"(?P<fraction>[0-9]+/[0-9]+)|(?P<atom>{_ATOM}(?:-{_ATOM})*)")
_STOPWORDS = frozenset(
    "a an and are as at be been by can do does for from has have how if in into is it its may must "
    "not of on or shall should than that the their then there these this those to was were what when "
    "where which who will with would".split()
)
# Unit spellings folded to one token, so "12 feet", "12-foot" and "12'" meet "12 ft" in a table
# header. Bare "in" stays a stopword (it is in nearly every chunk as a preposition); the unit
# forms "inches", "inch", "in." and the inch mark become the token "in".
_UNITS = {"feet": "ft", "foot": "ft", "ft": "ft", "inches": "in", "inch": "in", "percent": "pct", "pct": "pct"}
_UNIT_MARKS = (
    (re.compile(r"(?<=[0-9])\s*[\"”″]"), " inches "),  # 25.37" -> 25.37 in (" in " would be dropped as a stopword)
    (re.compile(r"(?<=[0-9])\s*['’′](?![a-z])"), " ft "),  # 12' -> 12 ft (not 12's)
    (re.compile(r"(?<=[0-9])\s*in\.(?![0-9])"), " inches "),  # "6 in." (not a sentence ending "plugs in.")
    (re.compile(r"(?<=[0-9]),(?=[0-9]{3}\b)"), ""),  # 1,500 -> 1500, as the manuals write both
    (re.compile(r"%"), " pct "),
)


def _normalise(text: str) -> str:
    text = text.lower()
    for pattern, replacement in _UNIT_MARKS:
        text = pattern.sub(replacement, text)
    return text


def _word(token: str) -> Optional[str]:
    """A single atom as a term: unit spellings folded, stopwords dropped, a plural "s" dropped ("closures" -> "closure")."""
    if token in _STOPWORDS:
        return None
    if token in _UNITS:
        return _UNITS[token]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss") and token[0].isalpha():
        token = token[:-1]
    return token


def tokens(text: str, parts: bool = True) -> List[str]:
    """Lower-cased words and numbers without stopwords, units folded, identifiers kept whole.

    A hyphenated identifier with a digit in it ("6H-3", "3-2", "A-3", "04-20340",
    "W8-11") and a fraction ("1/2") stay one token, so "Table 3-2" keeps its
    identity instead of becoming "3" and "2", which every table page holds. Their
    pieces follow as tokens of their own (with `parts`), so a chunk writing
    "Table 3 2" or "Figure 5-1b" is still found by the pieces. A hyphenated
    word without a digit ("right-of-way", "drop-off") is just its words, as the
    manuals hyphenate the same phrase inconsistently.
    """
    out: List[str] = []
    for match in _TOKEN.finditer(_normalise(text)):
        token = match.group(0)
        if match.group("fraction"):
            out.append(token)
            if parts:
                out.extend(token.split("/"))
            continue
        pieces = token.split("-")
        if len(pieces) > 1 and any(ch.isdigit() for ch in token):
            out.append(token)
            if not parts:
                continue
        elif len(pieces) == 1:
            word = _word(token)
            if word is not None:
                out.append(word)
            continue
        for piece in pieces:
            word = _word(piece)
            if word is not None:
                out.append(word)
    return out


def _postings(texts: Sequence[str], divisions: Sequence[Optional[str]]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """BM25 postings (terms, starts, rows, weights) of these texts, IDF and length norm per division."""
    counts = [Counter(tokens(t)) for t in texts]
    lengths = np.array([sum(c.values()) for c in counts], dtype=np.float64)
    by_division: Dict[Optional[str], List[int]] = {}
    for i, division in enumerate(divisions):
        by_division.setdefault(division, []).append(i)
    postings: Dict[str, List[Tuple[int, float]]] = {}
    for members in by_division.values():
        avg = max(lengths[members].mean(), 1.0)
        df = Counter(term for i in members for term in counts[i])
        n = len(members)
        for i in members:
            norm = K1 * (1 - B + B * lengths[i] / avg)
            for term, tf in counts[i].items():
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                postings.setdefault(term, []).append((i, idf * tf * (K1 + 1) / (tf + norm)))
    terms = sorted(postings)
    starts = np.zeros(len(terms) + 1, dtype=np.int64)
    rows: List[int] = []
    weights: List[float] = []
    for j, term in enumerate(terms):
        for i, weight in postings[term]:
            rows.append(i)
            weights.append(weight)
        starts[j + 1] = len(rows)
    return np.array(terms), starts, np.array(rows, dtype=np.int32), np.array(weights, dtype=np.float32)


class _Field:
    """One BM25 field: its postings and a term lookup."""

    def __init__(self, terms: np.ndarray, starts: np.ndarray, rows: np.ndarray, weights: np.ndarray):
        self.terms = terms
        self.starts = starts
        self.rows = rows
        self.weights = weights.astype(np.float32)
        self._lookup = {str(t): i for i, t in enumerate(terms)}

    def add(self, out: np.ndarray, term: str, factor: float = 1.0) -> None:
        j = self._lookup.get(term)
        if j is not None:
            a, b = self.starts[j], self.starts[j + 1]
            out[self.rows[a:b]] += self.weights[a:b] * factor

    def max_row(self) -> int:
        return int(self.rows.max()) if len(self.rows) else -1


class KeywordIndex:
    def __init__(self, terms: np.ndarray, starts: np.ndarray, rows: np.ndarray, weights: np.ndarray, n_chunks: int,
                 field: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = None, version: int = VERSION):
        self.body = _Field(terms, starts, rows, weights)
        self.field = _Field(*field) if field is not None else None
        self.n_chunks = n_chunks
        self.version = version  # of the file it was loaded from (1: DAR-651's, no field, old tokenizer)

    # The body's arrays, as saved; kept as attributes for the tools that inspect the index.
    terms = property(lambda self: self.body.terms)
    starts = property(lambda self: self.body.starts)
    rows = property(lambda self: self.body.rows)
    weights = property(lambda self: self.body.weights)

    @classmethod
    def build(cls, texts: Sequence[str], divisions: Sequence[Optional[str]],
              field_texts: Optional[Sequence[str]] = None) -> "KeywordIndex":
        """The index of these chunk texts; `divisions[i]` is chunk i's division, `field_texts[i]` its caption/ID field."""
        field = _postings(field_texts, divisions) if field_texts is not None else None
        return cls(*_postings(texts, divisions), len(texts), field=field)

    @classmethod
    def load(cls, directory: "str | Path", n_chunks: int) -> Optional["KeywordIndex"]:
        """The saved index, or None when the directory has none (an index built before it existed).

        A version-1 file (DAR-651) has no version entry and no field arrays: it
        loads with version 1, and IndexFile.load rebuilds it from the chunks.
        """
        path = Path(directory) / KEYWORD_FILE
        if not path.is_file():
            return None
        with np.load(path, allow_pickle=False) as data:
            field = None
            if "field_terms" in data:
                field = (data["field_terms"], data["field_starts"], data["field_rows"], data["field_weights"])
            version = int(data["version"]) if "version" in data else 1
            index = cls(data["terms"], data["starts"], data["rows"], data["weights"], n_chunks, field=field,
                        version=version)
        top = max(index.body.max_row(), index.field.max_row() if index.field else -1)
        if top >= n_chunks:
            raise ValueError(f"{KEYWORD_FILE} refers to chunk {top} but the index has {n_chunks}")
        return index

    def save(self, directory: "str | Path") -> None:
        arrays = dict(version=np.array(VERSION), terms=self.body.terms, starts=self.body.starts, rows=self.body.rows,
                      weights=self.body.weights.astype(np.float16))
        if self.field is not None:
            arrays.update(field_terms=self.field.terms, field_starts=self.field.starts, field_rows=self.field.rows,
                          field_weights=self.field.weights.astype(np.float16))
        np.savez_compressed(Path(directory) / KEYWORD_FILE, **arrays)

    def scores(self, query: str, field_boost: float = 0.0, ids: Sequence[str] = (), id_boost: float = 1.0) -> np.ndarray:
        """The query's score for every chunk: body BM25 + field_boost * field BM25 (0 where no query term occurs).

        `ids` are identifiers the question names ("Table 3-2", "04091", from
        query.parse): their number tokens ("3-2", not "table", which every
        captioned table has) count `id_boost` times in the field. With a
        field_boost of 0, or an index without a field, only the body counts.
        """
        out = np.zeros(self.n_chunks, dtype=np.float32)
        terms = set(tokens(query))
        for term in terms:
            self.body.add(out, term)
        if self.field is not None and field_boost > 0:
            boosted = {t for text in ids for t in tokens(text, parts=False) if any(ch.isdigit() for ch in t)}
            for term in terms | boosted:
                self.field.add(out, term, field_boost * (id_boost if term in boosted else 1.0))
        return out

    def top(self, query: str, rows: np.ndarray, k: int, field_boost: float = 0.0, ids: Sequence[str] = (),
            id_boost: float = 1.0) -> List[Tuple[int, float]]:
        """The k best of `rows` (chunk numbers) as (chunk number, score), only those matching a query term."""
        if not len(rows):
            return []
        scores = self.scores(query, field_boost, ids, id_boost)[rows]
        order = np.argsort(-scores, kind="stable")[:k]
        return [(int(rows[i]), float(scores[i])) for i in order if scores[i] > 0]


def fuse(rankings: Iterable[Sequence[int]], k: int = 60) -> List[int]:
    """Reciprocal rank fusion: items by the sum of 1 / (k + rank) over the rankings they appear in.

    k = 60 is the usual constant (Cormack et al., 2009); ties keep the order of
    first appearance, so the vector ranking wins a tie when it is passed first.
    """
    score: Dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            score[item] = score.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(score, key=lambda item: -score[item])
