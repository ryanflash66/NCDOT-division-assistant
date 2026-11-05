"""Separate searchable text for figures and drawings (DAR-658).

A figure's numbers are in its labels, which end up scattered through a page
chunk (or, for a sideways drawing, in the OCR block rag.ocr adds after the
page's text), far from the caption that names the figure. A figure chunk puts
the caption, the lines around it and the drawing's OCR labels together, so a
question naming the detail ("trailing end of a rigid obstacle", Detail 2B in
the guardrail manual, p. 12) finds one short passage that also holds the
labels ("L1 = N + 0.75 + LANE WIDTH").

No vision model writes descriptions here: that is a paid or hosted option
(Gemini, GPT-4o class, Mistral OCR) and needs Dr. Namian's approval. A local
VLM such as Granite-Docling-258M reads text on drawings but not the relations
between labels (LED-Bench: 31.8% on transportation drawings for the best model).
"""

import re
from typing import List, Tuple

# A figure or drawing caption on its own line: "Figure 5 – NC-PCB impact design
# table", "DETAIL 2B", "Exhibit 3-4 ...". Tables are left to the table chunks.
_FIGURE_CAPTION = re.compile(
    r"^\s*((?:Figure|FIGURE|Fig\.|FIG\.|Exhibit|EXHIBIT|Detail|DETAIL|Drawing|DRAWING|Plate|PLATE|Chart|CHART)"
    r"\s+[0-9A-Z][\w.\-]*\b.*?)\s*$"
)
# prototype.ingest.captions() names Figure/Table/Exhibit captions in a page's
# context line; a drawing's "DETAIL 2B" only gets its own figure chunk here.
# "Exhibit 3 shows the taper lengths ..." on a line of its own is prose, not a caption.
_PROSE = re.compile(r"^\S+\s+\S+\s+(?:shows?|illustrates?|presents?|summari[sz]es?|provides?|depicts?|lists?|"
                    r"gives?|is|are|was|were|contains?|describes?|includes?)\b", re.IGNORECASE)
_MIN_CAPTION_CHARS = 6  # "Figure 5", "DETAIL A"
# Longer lines that start "Figure 3 ..." are prose referring to a figure, not its caption.
_MAX_CAPTION_CHARS = 150
_NEARBY_LINES = 3
# bge-small and the reranker read the first 512 tokens; keep a figure chunk inside them.
MAX_FIGURE_CHARS = 1600
_OCR_BLOCK = re.compile(r"^OCR text \((?:page turned \d+ degrees|sideways labels)\):$")  # rag.ocr's headers
_MARKUP = re.compile(r"</?(?:u|mark|b|i|em|strong)>|\*\*|^#{1,6}\s+")


def _clean(line: str) -> str:
    return " ".join(_MARKUP.sub("", line.strip()).split())


def _lines(page_text: str) -> Tuple[List[str], List[str]]:
    """The page's non-empty lines (Markdown marks removed) and the lines of its turned-OCR block."""
    lines: List[str] = []
    labels: List[str] = []
    target = lines
    for raw in page_text.splitlines():
        line = _clean(raw)
        if not line:
            continue
        if _OCR_BLOCK.match(line):
            target = labels
            continue
        target.append(line)
    return lines + labels, labels


def figure_captions(page_text: str) -> List[str]:
    """The page's figure and drawing captions, in order, once each."""
    lines, _ = _lines(page_text)
    found = [m.group(1) for m in map(_FIGURE_CAPTION.match, lines)
             if m and _MIN_CAPTION_CHARS <= len(m.group(1)) <= _MAX_CAPTION_CHARS and not _PROSE.match(m.group(1))]
    return list(dict.fromkeys(found))


def figure_chunks(page_text: str) -> List[Tuple[str, str]]:
    """(caption, text) for each figure caption on the page: caption, nearby lines, then OCR labels."""
    lines, labels = _lines(page_text)
    out: List[Tuple[str, str]] = []
    for caption in figure_captions(page_text):
        i = lines.index(caption)
        nearby = lines[max(0, i - _NEARBY_LINES):i] + lines[i + 1:i + 1 + _NEARBY_LINES]
        parts = [caption] + nearby
        size = sum(len(p) + 1 for p in parts)
        for label in labels:
            if label in parts:
                continue
            if size + len(label) + 1 > MAX_FIGURE_CHARS:
                break
            parts.append(label)
            size += len(label) + 1
        out.append((caption, "\n".join(parts)[:MAX_FIGURE_CHARS]))
    return out
