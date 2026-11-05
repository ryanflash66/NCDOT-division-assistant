"""Keyword (BM25) search over the index's chunks, per division.

The vector search misses passages whose match is a number, a code or a rare
term the embedding blurs: a table cell such as "42.89", a drawing number, a
section "3.6.4.1". BM25 finds those by the words themselves. Its index is built
offline with the vector index (prototype.ingest) and saved next to it:

    bm25.npz   terms (sorted vocabulary), starts (offsets into the postings, one
               per term plus the end), rows (chunk numbers) and weights (the
               BM25 weight of the term in that chunk)

Each weight already holds the term's IDF and the chunk's length normalisation,
computed over the chunk's own division (k1 = 1.2, b = 0.75): a division is
searched on its own, so a term common in another division's manuals does not
make it rarer here. A query's score for a chunk is the sum of its terms'
weights. Like the vector search, only the asked division's rows (and the
ticked documents) are ranked, so another division's chunk is never returned.
Only numpy is needed.
"""

import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

KEYWORD_FILE = "bm25.npz"
# BM25 defaults (Robertson's usual values). They are baked into the saved
# weights, so changing them (BM25_K1, BM25_B in config.py) takes a rebuild of
# bm25.npz: the file holds neither term counts nor chunk lengths, and
# recomputing them from the chunks takes 4.5 s for the 10,746 committed chunks,
# too long for a cold start.
K1 = 1.2
B = 0.75
# Reciprocal rank fusion constant (Cormack et al., 2009); RRF_K in config.py.
RRF_K = 60

# Words, and numbers with their decimals or section dots ("42.89", "3.6.4.1").
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*")
_STOPWORDS = frozenset(
    "a an and are as at be been by can do does for from has have how if in into is it its may must "
    "not of on or shall should than that the their then there these this those to was were what when "
    "where which who will with would".split()
)


def tokens(text: str) -> List[str]:
    """Lower-cased words and numbers without stopwords; a plural "s" is dropped ("closures" -> "closure")."""
    out = []
    for token in _TOKEN.findall(text.lower()):
        if token in _STOPWORDS:
            continue
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss") and token[0].isalpha():
            token = token[:-1]
        out.append(token)
    return out


class KeywordIndex:
    def __init__(self, terms: np.ndarray, starts: np.ndarray, rows: np.ndarray, weights: np.ndarray, n_chunks: int,
                 k1: float = K1, b: float = B):
        self.terms = terms
        self.starts = starts
        self.rows = rows
        self.weights = weights
        self.n_chunks = n_chunks
        self.k1 = k1  # the BM25 parameters the weights were computed with
        self.b = b
        self._lookup = {str(t): i for i, t in enumerate(terms)}

    @classmethod
    def build(cls, texts: Sequence[str], divisions: Sequence[Optional[str]], k1: float = K1, b: float = B) -> "KeywordIndex":
        """The index of these chunk texts; `divisions[i]` is chunk i's division; `k1` and `b` are BM25's."""
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
                norm = k1 * (1 - b + b * lengths[i] / avg)
                for term, tf in counts[i].items():
                    idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                    postings.setdefault(term, []).append((i, idf * tf * (k1 + 1) / (tf + norm)))
        terms = sorted(postings)
        starts = np.zeros(len(terms) + 1, dtype=np.int64)
        rows: List[int] = []
        weights: List[float] = []
        for j, term in enumerate(terms):
            for i, weight in postings[term]:
                rows.append(i)
                weights.append(weight)
            starts[j + 1] = len(rows)
        return cls(np.array(terms), starts, np.array(rows, dtype=np.int32),
                   np.array(weights, dtype=np.float32), len(texts), k1=k1, b=b)

    @classmethod
    def load(cls, directory: "str | Path", n_chunks: int) -> Optional["KeywordIndex"]:
        """The saved index, or None when the directory has none (an index built before it existed)."""
        path = Path(directory) / KEYWORD_FILE
        if not path.is_file():
            return None
        with np.load(path, allow_pickle=False) as data:
            # k1 and b were added in DAR-657; a file saved before then was built with the defaults.
            k1 = float(data["k1"]) if "k1" in data else K1
            b = float(data["b"]) if "b" in data else B
            index = cls(data["terms"], data["starts"], data["rows"], data["weights"].astype(np.float32), n_chunks,
                        k1=k1, b=b)
        if len(index.rows) and int(index.rows.max()) >= n_chunks:
            raise ValueError(f"{KEYWORD_FILE} refers to chunk {int(index.rows.max())} but the index has {n_chunks}")
        return index

    def save(self, directory: "str | Path") -> None:
        np.savez_compressed(Path(directory) / KEYWORD_FILE, terms=self.terms, starts=self.starts,
                            rows=self.rows, weights=self.weights.astype(np.float16),
                            k1=np.float64(self.k1), b=np.float64(self.b))

    def scores(self, query: str) -> np.ndarray:
        """The query's BM25 score for every chunk (0 where no query term occurs)."""
        out = np.zeros(self.n_chunks, dtype=np.float32)
        for term in set(tokens(query)):
            j = self._lookup.get(term)
            if j is not None:
                a, b = self.starts[j], self.starts[j + 1]
                out[self.rows[a:b]] += self.weights[a:b]
        return out

    def top(self, query: str, rows: np.ndarray, k: int) -> List[Tuple[int, float]]:
        """The k best of `rows` (chunk numbers) as (chunk number, score), only those matching a query term."""
        if not len(rows):
            return []
        scores = self.scores(query)[rows]
        order = np.argsort(-scores, kind="stable")[:k]
        return [(int(rows[i]), float(scores[i])) for i in order if scores[i] > 0]


def fuse(rankings: Iterable[Sequence[int]], k: int = RRF_K, weights: Optional[Sequence[float]] = None) -> List[int]:
    """Reciprocal rank fusion: items by the sum of w / (k + rank) over the rankings they appear in.

    k = 60 is the usual constant (Cormack et al., 2009); ties keep the order of
    first appearance, so the vector ranking wins a tie when it is passed first.
    `weights` gives each ranking's multiplier w (default 1 each); a ranking
    past the end of the list gets 1.
    """
    weights = list(weights or [])
    score: Dict[int, float] = {}
    for n, ranking in enumerate(rankings):
        w = weights[n] if n < len(weights) else 1.0
        for rank, item in enumerate(ranking, 1):
            score[item] = score.get(item, 0.0) + w / (k + rank)
    return sorted(score, key=lambda item: -score[item])
