"""Read each picture page a second way, from its image, and compare the two readings (DAR-739).

    py -m prototype.read_pages --estimate                 # count the pages and estimate the cost; no call
    py -m prototype.read_pages --page "utilities/010604.pdf:278" ...   # read a few pages first
    py -m prototype.read_pages --max-usd 15               # read every flagged page not read yet
    py -m prototype.read_pages --compare-only             # recompute the flags after an index rebuild

The pages read are the ones whose text in the index came out of a picture, as
page_images.reasons() names them: a scan read by OCR (`scan`), a page OCR had to
turn or whose text runs sideways (`rotated`), a drawing's picture text
(`picture`) and a figure's own chunk (`figure`). Table and caption pages whose
text came from the PDF's text layer are not read: their text is the printed
text. On the index of Nov 18 that is 1,189 of its 5,797 pages.

Each page is rendered (pymupdf, DPI dots per inch, grayscale JPEG) and sent to
OpenAI with TRANSCRIBE_PROMPT; the reply is the page's image reading. Its
numbers are compared with the page's text in the index (its chunks' text, the
OCR reading) by divrag.readings.compare(), and both go to
hosted/index/page_readings.json with the flag (`agree`, `disagree`,
`image_only`), the differences, and the call's tokens and cost. The file is
written after every page, so a run that stops is resumed by running it again:
pages already read are skipped (--force reads them again).

The key is OPENAI_API_KEY (read from the environment or .env, never written
anywhere); --base-url sends the calls to another OpenAI-compatible endpoint.
Every call's cost is added up from its `usage` at the model's price
(divrag.spend), and the run stops before a call that could take it past
--max-usd. These calls don't go through the site, so the site's monthly ledger
(DAR-715) doesn't see them: add the printed total to the month by hand.

--estimate makes no call: it counts the pages, sizes each one's image at --dpi,
and prices the input at the image tokens measured in DAR-733 (about 1,300 a
510 x 660 page, three times OpenAI's published patch count, so scaled by area)
and the output at the page's OCR text length.
"""

import argparse
import asyncio
import base64
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx
from dotenv import load_dotenv

from prototype import HOSTED_DIR
from divrag.divisions import DOCUMENTS_DIR, document_for
from divrag.page_images import load_no_text_pages, reasons
from divrag.readings import READINGS_FILE, compare
from divrag.spend import price_for, usage_tokens

INDEX_DIR = HOSTED_DIR / "index"
DATA_DIR = Path("data")
DEFAULT_MODEL = "gpt-6.1-terra"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
# The reasons a page is read for (page_images.REASON_ORDER): the text of these came out of a picture.
READ_REASONS = ("scan", "rotated", "picture", "figure")
# Dots per inch of the image sent. The Sources panel's 60 dpi renders read the five DAR-732 pages
# well enough (dar-733-cost-estimate.md); Dr. Namian put accuracy before cost (Nov 17), so the
# reading gets more: 100 dpi makes a letter page 850 x 1100, where a scanned table's small print is sharp.
DEFAULT_DPI = 100
# Longest side sent, in pixels: OpenAI scales a larger image down to fit 2048 anyway, so sending more
# costs upload time and nothing else (the plan sheets are 11 x 17 and larger).
MAX_SIDE = 2048
JPEG_QUALITY = 85
DETAIL = "high"
# Room for the longest pages: the densest flagged page's OCR text is about 20,000 characters.
MAX_COMPLETION_TOKENS = 8000
CONCURRENCY = 4
TIMEOUT_SECONDS = 180.0
# Input tokens of one image, from DAR-733's logs: about 1,300 extra input tokens a 510 x 660
# page image at detail auto (dar-733-page-images-run.md), against 404 by OpenAI's patch formula.
MEASURED_TOKENS_PER_PIXEL = 1300 / (510 * 660)
PATCH_TOKENS = 1.2  # OpenAI's vision guide: tokens per 32 x 32 patch for the current models
PROMPT_TOKENS = 450  # TRANSCRIBE_PROMPT and the page's label
CHARS_PER_TOKEN = 4
MARKDOWN_OVERHEAD = 1.3  # table bars and line breaks the transcription adds to the OCR text's length
NO_TEXT = "NO_TEXT"
PROMPT_VERSION = 1

TRANSCRIBE_PROMPT = """You transcribe one page of a transportation agency's manual from its image, for a search index whose answers engineers rely on. Write out all the text on the page exactly as printed, in reading order.

Rules:
- Copy every number, fraction, unit and symbol exactly. Write a built-up or stacked fraction as whole number, space, fraction: "1½" or a stacked one and a half is "1 1/2". Keep the ' and " marks for feet and inches, and the degree sign.
- Tables: one Markdown table per printed table, with its header row; one printed row per line, cells from left to right as printed. Repeat a merged cell's value in each row it spans.
- A page, table or label printed sideways: read it turned upright.
- Drawings, maps, sign details and charts: the caption, then each label, dimension and note, one per line, saying what it labels when the drawing shows it ("Bay taper: 150'").
- Keep headings, notes, footnotes, page numbers and revision dates. Skip nothing, add nothing, and do not explain or summarize.
- Where the print cannot be read, write [illegible] rather than guess.
- If the page has no text at all, reply NO_TEXT and nothing else."""


@dataclass(frozen=True)
class Page:
    """One page to read: where it is, why, and its text in the index (the OCR reading)."""

    division: str
    source: str
    page: int
    reasons: Tuple[str, ...]
    ocr_text: str

    @property
    def key(self) -> str:
        return f"{self.division}/{self.source}:{self.page}"


def _chunks(index_dir: Path) -> List[Dict[str, Any]]:
    data = json.loads((index_dir / "chunks.json").read_text(encoding="utf-8"))
    return data["chunks"] if isinstance(data, dict) else data


def flagged_pages(chunks: Sequence[Dict[str, Any]], no_text: Any) -> List[Page]:
    """The pages to read, in index order, each with its chunks' text.

    The OCR reading of a page is the text of every chunk that covers it (a table
    joined over a page break covers both pages), the figure chunks left out when
    the page has others: a figure chunk repeats its page's labels. Chunks overlap,
    so a line can come twice; compare() counts a number's presence, not how often.
    """
    why: Dict[Tuple[str, str, int], set] = {}
    texts: Dict[Tuple[str, str, int], List[Tuple[bool, str]]] = {}
    order: List[Tuple[str, str, int]] = []
    for chunk in chunks:
        division, source, first = chunk.get("division"), chunk.get("source"), chunk.get("page")
        if not (division and source and first):
            continue
        found = [r for r in reasons(chunk, no_text) if r in READ_REASONS]
        for page in range(int(first), int(chunk.get("page_end") or first) + 1):
            key = (division, source, page)
            if key not in texts:
                order.append(key)
            texts.setdefault(key, []).append((chunk.get("kind") == "figure", chunk.get("text") or ""))
            if found:
                why.setdefault(key, set()).update(found)
    pages = []
    for key in order:
        if key not in why:
            continue
        parts = texts[key]
        prose = [text for figure, text in parts if not figure]
        pages.append(Page(*key, tuple(r for r in READ_REASONS if r in why[key]),
                          "\n\n".join(prose or [text for _, text in parts])))
    return pages


def pdf_path(page: Page, documents_dir: Path, data_dir: Path = DATA_DIR) -> Optional[Path]:
    """The PDF a page is in: its division's folder (fetch_documents.py), else DATA_DIR, as prototype.ingest reads it."""
    for root in (documents_dir / page.division, data_dir):
        if (root / page.source).is_file():
            return root / page.source
    return None


def image_size(width_pt: float, height_pt: float, dpi: int) -> Tuple[int, int]:
    """The pixel size of a page of this many points at `dpi`, scaled down to MAX_SIDE."""
    w, h = width_pt * dpi / 72, height_pt * dpi / 72
    scale = min(1.0, MAX_SIDE / max(w, h))
    return max(1, round(w * scale)), max(1, round(h * scale))


def render(path: Path, page: int, dpi: int) -> bytes:
    """The page (1-based PDF index) as a grayscale JPEG at `dpi`, no side over MAX_SIDE."""
    import pymupdf  # installed with pymupdf4llm (requirements.txt); not a hosted dependency

    with pymupdf.open(path) as pdf:
        pdf_page = pdf[page - 1]
        width, height = image_size(pdf_page.rect.width, pdf_page.rect.height, dpi)
        zoom = min(width / pdf_page.rect.width, height / pdf_page.rect.height)
        pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
        return pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)


def page_points(path: Path, page: int) -> Tuple[float, float]:
    import pymupdf

    with pymupdf.open(path) as pdf:
        rect = pdf[page - 1].rect
        return rect.width, rect.height


def estimate_tokens(size: Tuple[int, int], ocr_chars: int) -> Dict[str, float]:
    """A page's (input, output) tokens, the input both by DAR-733's measured rate and by OpenAI's patch count."""
    width, height = size
    measured = width * height * MEASURED_TOKENS_PER_PIXEL
    patches = math.ceil(width / 32) * math.ceil(height / 32) * PATCH_TOKENS
    output = max(50.0, ocr_chars / CHARS_PER_TOKEN * MARKDOWN_OVERHEAD)
    return {"input_measured": measured + PROMPT_TOKENS, "input_patches": patches + PROMPT_TOKENS, "output": output}


def estimate(pages: Sequence[Page], documents_dir: Path, dpi: int, prices: Tuple[float, float]) -> Dict[str, Any]:
    """The cost of reading these pages, in dollars, under both input assumptions; no call is made."""
    totals = {"input_measured": 0.0, "input_patches": 0.0, "output": 0.0}
    missing, sizes = [], []
    for page in pages:
        path = pdf_path(page, documents_dir)
        if path is None:
            missing.append(page.key)
            continue
        size = image_size(*page_points(path, page.page), dpi)
        sizes.append(size)
        for name, value in estimate_tokens(size, len(page.ocr_text)).items():
            totals[name] += value
    price_in, price_out = prices
    usd_out = totals["output"] * price_out / 1e6
    by_reason: Dict[str, int] = {}
    for page in pages:
        by_reason[page.reasons[0]] = by_reason.get(page.reasons[0], 0) + 1
    return {
        "pages": len(pages), "missing_pdfs": missing, "dpi": dpi, "by_first_reason": by_reason,
        "tokens": {k: round(v) for k, v in totals.items()},
        "usd_measured_rate": round(totals["input_measured"] * price_in / 1e6 + usd_out, 2),
        "usd_patch_formula": round(totals["input_patches"] * price_in / 1e6 + usd_out, 2),
        "usd_output_doubled": round(totals["input_measured"] * price_in / 1e6 + 2 * usd_out, 2),
        "largest_image": max(sizes, key=lambda s: s[0] * s[1]) if sizes else None,
    }


class ReadingsFile:
    """hosted/index/page_readings.json: read, updated one page at a time, written after each."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.data = {}
        self.data.setdefault("pages", {})

    def get(self, page: Page) -> Optional[Dict[str, Any]]:
        return self.data["pages"].get(page.division, {}).get(page.source, {}).get(str(page.page))

    def put(self, page: Page, row: Dict[str, Any]) -> None:
        self.data["pages"].setdefault(page.division, {}).setdefault(page.source, {})[str(page.page)] = row

    def rows(self) -> Iterable[Dict[str, Any]]:
        for files in self.data["pages"].values():
            for by_page in files.values():
                yield from by_page.values()

    def save(self, meta: Dict[str, Any]) -> None:
        self.data.update(meta)
        rows = list(self.rows())
        self.data["totals"] = {
            "pages": len(rows),
            **{flag: sum(1 for r in rows if r.get("agreement") == flag)
               for flag in ("agree", "disagree", "image_only", "no_image_text")},
            "usd": round(sum(r.get("usd") or 0 for r in rows), 4),
        }
        ordered = {k: self.data[k] for k in sorted(self.data) if k != "pages"}
        ordered["pages"] = {d: {f: dict(sorted(p.items(), key=lambda kv: int(kv[0])))
                                for f, p in sorted(files.items())}
                            for d, files in sorted(self.data["pages"].items())}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(ordered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def flag(ocr_text: str, image_text: str) -> Tuple[str, List[List[str]]]:
    """compare(), with a reply of NO_TEXT kept apart: the model saw no text where OCR found some."""
    if not image_text.strip():
        return ("image_only" if not ocr_text.strip() else "no_image_text"), []
    agreement, differences = compare(ocr_text, image_text)
    return agreement, [list(d) for d in differences]


def _message(page: Page, jpeg: bytes) -> List[Dict[str, Any]]:
    document = document_for(page.source)
    title = document.title if document else page.source
    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    return [
        {"role": "system", "content": TRANSCRIBE_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": f"{title}, PDF page {page.page}."},
            {"type": "image_url", "image_url": {"url": url, "detail": DETAIL}},
        ]},
    ]


class Budget:
    """The run's spending: each call is admitted only while the worst case of another one still fits."""

    def __init__(self, max_usd: float, prices: Tuple[float, float]):
        self.max_usd = max_usd
        self.prices = prices
        self.spent = 0.0
        # A call's worst case: a large image's input and the full completion allowance.
        self.worst = (6000 * prices[0] + MAX_COMPLETION_TOKENS * prices[1]) / 1e6
        self.pending = 0

    def admit(self) -> bool:
        if self.spent + (self.pending + 1) * self.worst > self.max_usd:
            return False
        self.pending += 1
        return True

    def charge(self, tokens: Optional[Tuple[int, int]]) -> float:
        self.pending -= 1
        usd = ((tokens[0] * self.prices[0] + tokens[1] * self.prices[1]) / 1e6) if tokens else self.worst
        self.spent += usd
        return usd


async def read_page(client: httpx.AsyncClient, url: str, key: str, model: str, page: Page,
                    jpeg: bytes) -> Tuple[str, Optional[Tuple[int, int]], bool]:
    """The page's image reading, the call's (input, output) tokens and whether the reply was cut off."""
    body = {"model": model, "messages": _message(page, jpeg), "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "reasoning_effort": "none", "temperature": 0}
    response = await client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    choice = data["choices"][0]
    text = (choice.get("message") or {}).get("content") or ""
    text = "" if text.strip() == NO_TEXT else text.strip()
    return text, usage_tokens(data.get("usage")), choice.get("finish_reason") == "length"


async def read_all(pages: Sequence[Page], store: ReadingsFile, meta: Dict[str, Any], documents_dir: Path,
                   base_url: str, key: str, model: str, dpi: int, budget: Budget) -> Dict[str, int]:
    url = base_url.rstrip("/") + "/chat/completions"
    gate = asyncio.Semaphore(CONCURRENCY)
    counts = {"read": 0, "failed": 0, "skipped_budget": 0, "missing_pdf": 0}
    lock = asyncio.Lock()

    async def one(client: httpx.AsyncClient, page: Page) -> None:
        path = pdf_path(page, documents_dir)
        if path is None:
            counts["missing_pdf"] += 1
            print(f"  {page.key}: PDF not found under {documents_dir} or {DATA_DIR}")
            return
        async with gate:
            if not budget.admit():
                counts["skipped_budget"] += 1
                return
            jpeg = await asyncio.to_thread(render, path, page.page, dpi)
            started = time.perf_counter()
            try:
                text, tokens, cut_off = await read_page(client, url, key, model, page, jpeg)
            except Exception as exc:  # noqa: BLE001  one page failing must not lose the others
                budget.charge(None)  # counted at its worst case: the call may have been billed
                counts["failed"] += 1
                print(f"  {page.key}: failed ({exc.__class__.__name__}: {str(exc)[:160]})")
                return
            usd = budget.charge(tokens)
        agreement, differences = flag(page.ocr_text, text)
        row = {"image": text, "agreement": agreement, "differences": differences, "reasons": list(page.reasons),
               "model": model, "dpi": dpi, "prompt_version": PROMPT_VERSION,
               "input_tokens": tokens[0] if tokens else None, "output_tokens": tokens[1] if tokens else None,
               "usd": round(usd, 6), "seconds": round(time.perf_counter() - started, 1)}
        if cut_off:
            row["cut_off"] = True
        async with lock:
            store.put(page, row)
            store.save(meta)
            counts["read"] += 1
        print(f"  {page.key}: {agreement}{' (cut off)' if cut_off else ''}, {len(text)} chars, ${usd:.4f} "
              f"(run ${budget.spent:.2f})")

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        await asyncio.gather(*(one(client, page) for page in pages))
    return counts


def recompare(pages: Sequence[Page], store: ReadingsFile) -> int:
    """Recompute each read page's flag against the index's current text; how many changed."""
    changed = 0
    for page in pages:
        row = store.get(page)
        if row is None or not isinstance(row.get("image"), str):
            continue
        agreement, differences = flag(page.ocr_text, row["image"])
        if (agreement, differences) != (row.get("agreement"), row.get("differences")):
            changed += 1
            row.update(agreement=agreement, differences=differences)
    return changed


def _wanted(pages: List[Page], selected: Sequence[str]) -> List[Page]:
    """The pages named "division/file:page" (as Page.key prints them), in the order given."""
    by_key = {page.key: page for page in pages}
    unknown = [key for key in selected if key not in by_key]
    if unknown:
        raise SystemExit(f"not a flagged page of the index: {', '.join(unknown)}")
    return [by_key[key] for key in selected]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.read_pages", description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, default=INDEX_DIR, help=f"the index to read pages for (default {INDEX_DIR})")
    parser.add_argument("--documents", type=Path, default=DOCUMENTS_DIR, help=f"the divisions' PDFs (default {DOCUMENTS_DIR})")
    parser.add_argument("--estimate", action="store_true", help="count the pages and estimate the cost; no call")
    parser.add_argument("--compare-only", action="store_true", help="recompute the flags against the index's text; no call")
    parser.add_argument("--page", action="append", default=[], help='only this page, "division/file:page" (repeatable)')
    parser.add_argument("--limit", type=int, help="read at most this many pages not read yet")
    parser.add_argument("--force", action="store_true", help="read pages that already have a reading again")
    parser.add_argument("--max-usd", type=float, default=1.0, help="stop before a call that could take the run past this (default 1)")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"image resolution (default {DEFAULT_DPI})")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"OpenAI model (default {DEFAULT_MODEL})")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"OpenAI-compatible endpoint (default {DEFAULT_BASE_URL})")
    args = parser.parse_args(argv)

    load_dotenv()
    prices = price_for(args.model, os.environ)
    if prices is None:
        raise SystemExit(f"no known price for {args.model}: set OPENAI_PRICE_PER_MILLION to input,output dollars")
    pages = flagged_pages(_chunks(args.index), load_no_text_pages(args.index))
    if args.page:
        pages = _wanted(pages, args.page)
    store = ReadingsFile(args.index / READINGS_FILE)
    meta = {"model": args.model, "dpi": args.dpi, "detail": DETAIL, "prompt_version": PROMPT_VERSION,
            "reasons": list(READ_REASONS)}

    if args.estimate:
        todo = pages if args.force else [p for p in pages if store.get(p) is None]
        print(json.dumps(estimate(todo, args.documents, args.dpi, prices), indent=1))
        return 0
    if args.compare_only:
        changed = recompare(pages, store)
        store.save({})
        print(f"{changed} page flags changed; totals {store.data['totals']}")
        return 0

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set (environment or .env)")
    todo = pages if args.force else [p for p in pages if store.get(p) is None]
    if args.limit is not None:
        todo = todo[:args.limit]
    print(f"{len(pages)} flagged pages, {len(todo)} to read with {args.model} at {args.dpi} dpi, "
          f"at most ${args.max_usd:.2f}")
    budget = Budget(args.max_usd, prices)
    started = time.perf_counter()
    counts = asyncio.run(read_all(todo, store, meta, args.documents, args.base_url, key, args.model, args.dpi, budget))
    store.save(meta)
    print(f"{counts} in {time.perf_counter() - started:.0f}s, ${budget.spent:.2f} this run; "
          f"file totals {store.data['totals']}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
