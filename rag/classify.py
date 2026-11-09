"""Document classification: NCDOT topic labels derived from a Document's relative path.

The path is split into lowercase alphanumeric tokens (the file extension is
dropped). A keyword matches a token exactly; keywords of four or more characters
also match as a token prefix, so "encroach" matches "encroachments" while "tim"
never matches "timeline" or "estimate". Multi-word keywords match consecutive
tokens. When several topic labels match, the most specific keyword wins (more
words, then more characters); ties go to the earlier label in TOPIC_KEYWORDS.
Content, the absolute path and the repository location never affect the result.
"""

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, List, Sequence, Tuple

_PREFIX_MIN_LEN = 4

TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "work_zone": [
        "work zone", "wz", "wztc", "tmp", "ttc", "temporary traffic control",
        "flagging", "flagger", "lane closure", "detour", "positive protection",
    ],
    "utilities": ["utilit", "uam", "encroach", "directional drilling", "frac out", "right of way"],
    "mobility_safety": ["mobility", "safety", "tmsd", "crash", "traffic incident management", "tim"],
    "signals_signing": ["signal", "signing", "signs", "pavement marking", "its", "tods"],
    "roadside": ["guardrail", "barrier", "clear zone", "attenuator", "roadside"],
    "construction": ["construction", "specification", "roads and structures", "bridge", "pavement"],
}

# Paths naming one of these are NCDOT reference documents (manuals, guidance, policy).
REFERENCE_KEYWORDS: List[str] = [
    "manual",
    "handbook",
    "guide",
    "specification",
    "standard",
    "policy",
    "procedure",
    "sop",
    "memo",
    "directive",
    "provision",
    "chapter",
]

# The Roadway Standard Drawings are a set of their own: sheets of details, not
# prose, so they get their own domain instead of a topic.
STANDARD_DRAWINGS_KEYWORD = "standard drawing"


@dataclass(frozen=True)
class DocClassification:
    topic: str
    doc_domain: str
    tags: str

    def as_metadata(self) -> Dict[str, str]:
        return {
            "topic": self.topic,
            "doc_domain": self.doc_domain,
            "tags": self.tags,
        }


def _tokens(relative_path: PurePath) -> Tuple[str, ...]:
    stem = relative_path.with_suffix("") if relative_path.suffix else relative_path
    return tuple(re.findall(r"[a-z0-9]+", stem.as_posix().lower()))


def _token_matches(keyword_token: str, token: str) -> bool:
    if len(keyword_token) >= _PREFIX_MIN_LEN:
        return token.startswith(keyword_token)
    return token == keyword_token


def _matches(keyword: str, tokens: Sequence[str]) -> bool:
    parts = keyword.split()
    for start in range(len(tokens) - len(parts) + 1):
        window = tokens[start:start + len(parts)]
        # Every token but the last must match exactly; the last may be a prefix.
        if all(a == b for a, b in zip(parts[:-1], window[:-1])) and _token_matches(parts[-1], window[-1]):
            return True
    return False


def _any(keywords: Sequence[str], tokens: Sequence[str]) -> bool:
    return any(_matches(keyword, tokens) for keyword in keywords)


def _best_match(keywords: Sequence[str], tokens: Sequence[str]) -> Tuple[int, int]:
    """Specificity of the longest matching keyword as (words, chars); (0, 0) if none."""
    return max(
        ((len(k.split()), len(k)) for k in keywords if _matches(k, tokens)),
        default=(0, 0),
    )


def classify(relative_path: "str | PurePath") -> DocClassification:
    """Classify a Document by its path relative to the data directory."""
    tokens = _tokens(PurePath(relative_path))

    if _matches(STANDARD_DRAWINGS_KEYWORD, tokens):
        return DocClassification(
            topic="general",
            doc_domain="standard_drawings",
            tags="standard,drawings",
        )

    scores = {label: _best_match(keywords, tokens) for label, keywords in TOPIC_KEYWORDS.items()}
    matched = [label for label, score in scores.items() if score > (0, 0)]
    # Most specific keyword wins; max() keeps the first label (dict order) on ties.
    topic = max(matched, key=scores.__getitem__) if matched else "unknown"
    doc_domain = "reference" if _any(REFERENCE_KEYWORDS, tokens) else "general"
    tags = matched + (["reference"] if doc_domain == "reference" else [])

    return DocClassification(
        topic=topic,
        doc_domain=doc_domain,
        tags=",".join(tags) if tags else "none",
    )
