"""OCR for PDF pages that tries the page's four orientations (DAR-658).

pymupdf4llm calls an `ocr_function(page, dpi=..., ...)` on the pages it judges
to need OCR. Its RapidOCR callback reads the page image as rendered. RapidOCR
only fixes 180 degree flips per line and turns every tall crop the same way, so
a drawing laid out sideways reads in fragments: the guardrail manual's Detail
2B (03. Guardrail, Barriers and Attenuators.pdf p. 12, the tmsd-guardrail-l1
question) gave 506 characters at mean confidence 0.81 upright and 793 at 0.96
turned 90 degrees clockwise.

RapidOCR does read a tall (sideways) line box, but pymupdf4llm then writes the
text back across the box's narrow width and its Markdown comes out garbled: a
synthetic sideways page "LENGTH OF NEED 350 FEET" became "LENGTH OF N **E** D
350 F **E** T". So a sideways line counts for nothing when readings are compared.

`OrientedOcr` is a drop-in `ocr_function`: it reads the page in the orientation
the text layer suggests first (line direction plus page rotation), and when the
mean line confidence is below OCR_RETRY_BELOW or sideways lines carry much of
the text, it reads the other three and keeps the reading with the most confident
level text. An upright reading's level lines go back into the page exactly as
pymupdf4llm's own callback puts them (text at each line's box); a turned
reading, and an upright reading's sideways lines, can't be placed on the page
that way, so their rows are kept on `pages` for the reader to add after the
page's Markdown. Each page's choice and confidence are kept on `pages` too, so
the index can flag pages OCR read badly.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

# Below this mean line confidence the other orientations are tried. Upright
# scanned text pages read at 0.97-0.99 (the Revised Rumble Strip Guidelines memo,
# Chapter 5 of the work zone manual); the sideways guardrail detail read at 0.81.
OCR_RETRY_BELOW = 0.9
# Below this mean confidence, even the best orientation is flagged "ocr_low_conf".
OCR_LOW_CONFIDENCE = 0.8
# Retry when more than this share of a reading's characters are in sideways boxes.
OCR_SIDEWAYS_SHARE = 0.3
TURNED_HEADER = "OCR text (page turned {} degrees):"
SIDEWAYS_HEADER = "OCR text (sideways labels):"

Line = Tuple[Sequence, str, float]  # (box: 4 points, text, confidence), as pymupdf4llm's full_ocr returns
Reader = Callable[[np.ndarray], List[Line]]


def sideways(line: Line) -> bool:
    """A box taller than wide holding more than a couple of characters: text running up or down the image."""
    box, text, _ = line
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return len(text.strip()) > 2 and (max(ys) - min(ys)) > 1.5 * (max(xs) - min(xs))


@dataclass
class Reading:
    """One orientation's OCR: `turns` quarter turns counter-clockwise (np.rot90) were applied first."""

    turns: int
    lines: List[Line] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        return float(np.mean([s for _, _, s in self.lines])) if self.lines else 0.0

    @property
    def weight(self) -> float:
        # Confident characters on level lines: a wrong orientation reads fewer,
        # shorter lines, and sideways lines can't go back onto the page.
        return float(sum(len(line[1].strip()) * line[2] for line in self.lines if not sideways(line)))

    @property
    def sideways_share(self) -> float:
        total = sum(len(t.strip()) for _, t, _ in self.lines)
        return sum(len(line[1].strip()) for line in self.lines if sideways(line)) / total if total else 0.0

    @property
    def degrees(self) -> int:
        """How far the image was turned counter-clockwise before this reading, in degrees."""
        return (self.turns * 90) % 360


@dataclass
class PageOcr:
    """What OCR did on one page (0-based `number`, as pymupdf numbers pages)."""

    number: int
    degrees: int  # counter-clockwise turn applied to the image before the kept reading
    confidence: float
    tried: List[int]
    lines: List[str]  # the kept reading's text, one row per entry, top to bottom
    extra: List[str] = field(default_factory=list)  # rows not written back onto the page (the reader appends them)

    @property
    def flags(self) -> List[str]:
        out = []
        if self.lines and self.confidence < OCR_LOW_CONFIDENCE:
            out.append("ocr_low_conf")
        if self.degrees:
            out.append("rotated")
        return out


def orientation_hint(page) -> int:
    """Quarter turns (np.rot90's k) that should make the rendered page's text upright; 0 when unknown.

    The text layer's dominant line direction is in unrotated page space (y down):
    (1, 0) upright, (0, -1) reading upward, (0, 1) downward, (-1, 0) upside down.
    The page's /Rotate turns the rendered image clockwise on top of that.
    pymupdf4llm removes /Rotate before it calls the OCR function, so there the
    line direction alone decides; the rotation term is for a page as opened.
    """
    chars: Counter = Counter()
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            dx, dy = line["dir"]
            angle = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}.get((round(dx), round(dy)))
            if angle is not None:
                chars[angle] += sum(len(s["text"].strip()) for s in line["spans"])
    top = chars.most_common(1)
    angle = top[0][0] if top and top[0][1] > 0 else 0
    return ((page.rotation - angle) // 90) % 4


def read_oriented(img: np.ndarray, read: Reader, first: int = 0,
                  retry_below: float = OCR_RETRY_BELOW) -> Tuple[Reading, List[int]]:
    """The best reading of the image and the orientations tried (degrees), `first` first."""
    order = [first % 4] + [k for k in range(4) if k != first % 4]
    best: Optional[Reading] = None
    tried = []
    for turns in order:
        reading = Reading(turns, list(read(np.ascontiguousarray(np.rot90(img, turns))) or []))
        tried.append(turns * 90)
        if best is None or reading.weight > best.weight:
            best = reading
        if best.lines and best.confidence >= retry_below and best.sideways_share <= OCR_SIDEWAYS_SHARE:
            break
    return best, tried


def rows(lines: Sequence[Line]) -> List[str]:
    """Line texts grouped into rows (boxes whose vertical centres are within half a box height), top to bottom."""
    boxes = []
    for box, text, _ in lines:
        if not text.strip():
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append(((min(ys) + max(ys)) / 2, max(max(ys) - min(ys), 1), min(xs), text.strip()))
    boxes.sort()
    out: List[List[Tuple[float, str]]] = []
    centre = height = 0.0
    for y, h, x, text in boxes:
        if out and abs(y - centre) <= height / 2:
            out[-1].append((x, text))
        else:
            out.append([(x, text)])
            centre, height = y, h
    return ["  ".join(t for _, t in sorted(row)) for row in out]


def _default_reader() -> Reader:
    from pymupdf4llm.ocr import rapidocr_api

    if rapidocr_api.full_ocr is None:
        raise RuntimeError("RapidOCR is not installed (pip install rapidocr onnxruntime)")
    return rapidocr_api.full_ocr


class OrientedOcr:
    """pymupdf4llm `ocr_function` that tries the four orientations; see the module docstring."""

    def __init__(self, read: Optional[Reader] = None, retry_below: float = OCR_RETRY_BELOW):
        self._read = read
        self._retry_below = retry_below
        self.pages: Dict[int, PageOcr] = {}

    def __call__(self, page, dpi: int = 150, pixmap=None, language=None, keep_ocr_text: bool = False):
        from pymupdf4llm.ocr.exec_ocr_interface import exec_ocr_full

        read = self._read or _default_reader()
        first = orientation_hint(page)

        def full_ocr(img: np.ndarray) -> List[Line]:
            best, tried = read_oriented(img, read, first, self._retry_below)
            # A turned reading's boxes are in the turned image, and a sideways line
            # comes out garbled when written back: the reader appends their text instead.
            placed = [line for line in best.lines if not sideways(line)] if best.turns == 0 else []
            kept = [line for line in best.lines if best.turns != 0 or sideways(line)]
            self.pages[page.number] = PageOcr(page.number, best.degrees, best.confidence, tried,
                                              rows(best.lines), rows(kept))
            return placed

        return exec_ocr_full(page, full_ocr, dpi=dpi, language=language, keep_ocr_text=keep_ocr_text)

    def appended_text(self, number: int) -> str:
        """The block the reader appends to the page: OCR rows that weren't written onto it; "" when none."""
        result = self.pages.get(number)
        if result is None or not result.extra:
            return ""
        header = TURNED_HEADER.format(result.degrees) if result.degrees else SIDEWAYS_HEADER
        return header + "\n" + "\n".join(result.extra)
