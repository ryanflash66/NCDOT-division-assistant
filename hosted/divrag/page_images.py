"""The page images sent to the model with the passages they come from (DAR-733, PAGE_IMAGES_TO_MODEL).

The model reads each passage as text the index build pulled out of the PDF.
On some pages that text is a poor copy of the page: a scan or drawing read by
OCR, a table printed sideways, a table flattened into rows. In the DAR-732
investigation 5 of the 6 wrong values came from pages whose text OCR read:
it read "1 ½" as "1/½2" (utilities-h056, a scanned permit) and gave a
sideways table's row right to left, so the model took 200 ft from the wrong
column for a 150 ft bay taper (tmsd-h052). The page image has neither problem.

A passage's page is sent when the passage, or a chunk merged into it, comes
from (see reasons()):

    scan      a page with no text layer, read by OCR (no_text_pages.json beside
              the index, written by prototype.ingest: chunks.json keeps no mark
              of a page OCR read well)
    rotated   a page OCR had to turn, or whose text runs sideways (the chunk's `flags`)
    picture   text read out of a picture on the page (pymupdf4llm's "picture text"
              marks): a drawing, map or sign whose labels lost their places
              (the Guardrail chapter's Figure 1 has a text header, so it is not
              a scan, but its slopes are picture text: tmsd-h049)
    figure    a figure or drawing caption's chunk (`kind: "figure"`)
    table     a table chunk
    caption   a chunk of a page that prints a figure or table caption (its `context` line)

The images are the ones the Sources panel shows (DAR-654/665: 60 dpi
grayscale JPEGs, 510 x 660 for a letter page, about 43 KB). At 60 dpi the
five DAR-732 pages read clearly, the "1 ½" and the sideways table included.
They are static files: on Vercel the CDN serves public/pages/ and vercel.json
keeps it out of the function bundle (247.5 MB would not fit beside the 340 MB
already there). So a page is read from disk when it is there (a local
checkout after a render) and otherwise fetched over HTTP from `base_url` (the
deployment itself, see base_url_from_env), and only pages the
render manifest lists are asked for. A page that can't be had within
FETCH_TIMEOUT_SECONDS is left out, never the answer: the passage text still goes.

The images ride on the user message under a private "images" key. Only
OpenAIClient turns them into image parts (openai_messages); OpenRouterClient
drops them (text_messages), so the free fallback models, which may not read
images, get exactly the prompt they got before.
"""

import asyncio
import base64
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import httpx

from .divisions import document_for
from .index_file import Hit
from .pages_static import PAGES_DIR, page_image_path, rendered, slug
from .retrieval import is_table

log = logging.getLogger(__name__)

NO_TEXT_FILE = "no_text_pages.json"
# OpenAI's image detail levels (Chat Completions image_url.detail). For the patch-based
# models (OpenAI's vision guide, read 2026-11-17) "auto", "high" and "original" all keep a
# 510 x 660 page whole: 16 x 21 patches of 32 px x 1.2 = 404 tokens. "low" fits it in
# 512 x 512 (396 x 512, 250 tokens), and the small print of a scanned table starts to blur.
DETAILS = ("auto", "low", "high", "original")
DEFAULT_DETAIL = "auto"
# Images per model call. Over the held-out set's 286 questions on the local index, 197 have a
# qualifying page, 1.71 a question and at most 7: 4 a call sends 463 of the 488 (1.62 a question,
# about $0.00065), 3 sends 420, and 5 or more adds almost nothing (docs/redo-reports/dar-733-cost-estimate.md).
DEFAULT_MAX_IMAGES = 4
MAX_IMAGES_LIMIT = 10
# All of a question's pages are fetched at once, and the answer doesn't wait longer than this
# for them: a CDN hit takes tens of milliseconds, and the 60 s request budget is the model's.
FETCH_TIMEOUT_SECONDS = 3.0
# Pages kept in memory per instance (about 43 KB each, so about 11 MB at most).
CACHE_PAGES = 256
# Biggest page image accepted: the largest of the 5,797 rendered pages is far under it.
MAX_IMAGE_BYTES = 1_000_000
# Pages that qualify for one reason before pages that qualify for another: the text of a scan
# or a sideways page is the least trustworthy copy of it, a table's or a captioned page's the most.
REASON_ORDER = ("scan", "rotated", "picture", "figure", "table", "caption")
_PICTURE_TEXT = "<!-- Start of picture text -->"

INTRO = ("Page images follow: the PDF page each of the passages below comes from, labelled with the "
         "passage's number. A passage's text was extracted from its page and can be garbled on scans, "
         "drawings and tables, especially sideways ones (fractions lost, columns out of order). When a page "
         "image shows a value more clearly than its passage's text, take the value from the image and cite "
         "that passage's number as usual. The images are the same pages as the passages, not other sources: "
         "every rule above still applies.")


@dataclass(frozen=True)
class PageRef:
    """One page to show the model: passage `n` reads from `page` of `source` in `division`."""

    n: int
    division: str
    source: str
    page: int
    reason: str
    score: float

    @property
    def key(self) -> Tuple[str, str, int]:
        return self.division, self.source, self.page

    def label(self) -> str:
        document = document_for(self.source)
        title = document.title if document else self.source
        return f"Page image for passage [{self.n}]: {title}, PDF page {self.page}"


NoText = Mapping[Tuple[str, str], Set[int]]


def load_no_text_pages(index_dir: Path) -> Dict[Tuple[str, str], Set[int]]:
    """The index's no_text_pages.json as {(division, file): pages}; empty when it is missing or unreadable.

    Missing costs only the "scan" reason: those pages' figure and table chunks still qualify.
    """
    path = Path(index_dir) / NO_TEXT_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {(str(division), str(file)): {int(p) for p in pages}
                for division, files in data.items() for file, pages in files.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, AttributeError, TypeError):
        log.warning("%s is unreadable; no page counts as scanned", path)
        return {}


def reasons(chunk: Dict[str, Any], no_text: NoText) -> List[str]:
    """Why the chunk's page should go to the model as an image (REASON_ORDER order); empty when it shouldn't."""
    found = set()
    division, source, page = chunk.get("division"), chunk.get("source"), chunk.get("page")
    if division and source and page and int(page) in no_text.get((division, source), ()):
        found.add("scan")
    flags = chunk.get("flags") or ()
    if "rotated" in flags or "ocr_low_conf" in flags:
        found.add("rotated" if "rotated" in flags else "scan")
    if _PICTURE_TEXT in (chunk.get("text") or ""):
        found.add("picture")
    if chunk.get("kind") == "figure":
        found.add("figure")
    if is_table(chunk):
        found.add("table")
    if chunk.get("context"):
        found.add("caption")
    return [r for r in REASON_ORDER if r in found]


def wanted_pages(hits: Sequence[Hit], no_text: NoText, start: int = 1) -> List[PageRef]:
    """The qualifying pages of the passages numbered from `start`, one per page, best first.

    Each part of a merged passage is looked at on its own (a table merged with
    the prose before it still brings its page), and a table joined over a page
    break brings each of its pages. Order: by reason (REASON_ORDER), then by the
    passage's reranker score, then passage number and page, so a cap keeps the
    pages whose text is least to be trusted and, among those, the best-ranked.
    """
    seen: Dict[Tuple[str, str, int], PageRef] = {}
    for n, hit in enumerate(hits, start):
        for part in hit.chunk.get("parts", [hit.chunk]):
            why = reasons(part, no_text)
            if not (why and part.get("page") and part.get("division") and part.get("source")):
                continue
            first = int(part["page"])
            for page in range(first, int(part.get("page_end") or first) + 1):
                ref = PageRef(n, part["division"], part["source"], page, why[0], hit.score)
                old = seen.get(ref.key)
                if old is None or _rank(ref) < _rank(old):
                    seen[ref.key] = ref
    return sorted(seen.values(), key=_rank)


def _rank(ref: PageRef) -> Tuple[int, float, int, int]:
    return REASON_ORDER.index(ref.reason), -ref.score, ref.n, ref.page


class PageImages:
    """Loads the page images for a question's passages and puts them on its user message."""

    def __init__(self, no_text: NoText, base_url: Optional[str] = None, detail: str = DEFAULT_DETAIL,
                 max_images: int = DEFAULT_MAX_IMAGES, headers: Optional[Mapping[str, str]] = None,
                 pages_dir: Path = PAGES_DIR, transport: "httpx.AsyncBaseTransport | None" = None,
                 listed: Callable[[], Mapping[str, Iterable[int]]] = rendered):
        if detail not in DETAILS:
            raise ValueError(f"detail must be one of {DETAILS}, got {detail!r}")
        self.no_text = no_text
        self.base_url = base_url.rstrip("/") if base_url else None
        self.detail = detail
        self.max_images = max_images
        self._headers = dict(headers or {})
        self._pages_dir = Path(pages_dir)
        self._transport = transport
        self._listed = listed
        self._cache: "OrderedDict[Tuple[str, str, int], bytes]" = OrderedDict()

    def pick(self, hits: Sequence[Hit], start: int = 1) -> List[PageRef]:
        """The pages to send for these passages: qualifying, rendered, at most max_images."""
        listed = self._listed()
        refs = [r for r in wanted_pages(hits, self.no_text, start)
                if r.page in listed.get(f"{r.division}/{slug(r.source)}", ())]
        return refs[:self.max_images]

    async def attach(self, message: Dict[str, Any], hits: Sequence[Hit], start: int = 1) -> Dict[str, Any]:
        """`message` with the images of its passages' pages under "images"; unchanged when none could be loaded.

        `start` is the number of the first of `hits` in the prompt (the second
        look after a refusal numbers its passages after the first ones).
        """
        refs = self.pick(hits, start)
        if not refs:
            return message
        try:
            loaded = await asyncio.wait_for(asyncio.gather(*(self._load(r) for r in refs)), FETCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            log.warning("page images: none within %.0f s; answering from the passage text", FETCH_TIMEOUT_SECONDS)
            return message
        images = [{"label": ref.label(), "url": "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii"),
                   "detail": self.detail}
                  for ref, data in zip(refs, loaded) if data]
        log.info("page images: %d of %d sent (%s)", len(images), len(refs),
                 ", ".join(f"[{r.n}] p.{r.page} {r.reason}" for r, d in zip(refs, loaded) if d))
        if not images:
            return message
        return dict(message, images=list(message.get("images") or []) + images)

    async def _load(self, ref: PageRef) -> Optional[bytes]:
        if ref.key in self._cache:
            self._cache.move_to_end(ref.key)
            return self._cache[ref.key]
        path = page_image_path(ref.division, ref.source, ref.page)
        data = self._from_disk(path)
        if data is None and self.base_url:
            data = await self._from_url(f"{self.base_url}/pages/{path}")
        if data:
            self._cache[ref.key] = data
            while len(self._cache) > CACHE_PAGES:
                self._cache.popitem(last=False)
        return data

    def _from_disk(self, path: str) -> Optional[bytes]:
        file = self._pages_dir / path
        try:
            return _jpeg(file.read_bytes()) if file.is_file() else None
        except OSError:
            return None

    async def _from_url(self, url: str) -> Optional[bytes]:
        try:
            async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, transport=self._transport,
                                         follow_redirects=False) as client:
                response = await client.get(url, headers=self._headers)
        except httpx.HTTPError as exc:
            log.warning("page image %s not fetched: %s", url, exc.__class__.__name__)
            return None
        if response.status_code != 200:
            # A protected preview answers 401 with a login page; that must not reach the model as an image.
            log.warning("page image %s not fetched: HTTP %s", url, response.status_code)
            return None
        return _jpeg(response.content)


def _jpeg(data: bytes) -> Optional[bytes]:
    """The bytes when they are a JPEG of a sensible size (the renders are), else None."""
    return data if data[:3] == b"\xff\xd8\xff" and len(data) <= MAX_IMAGE_BYTES else None


def text_messages(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The messages without their page images: what a model that doesn't read images is sent."""
    return [{k: v for k, v in m.items() if k != "images"} if "images" in m else m for m in messages]


def openai_messages(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The messages with each one's page images as Chat Completions content parts, after its text.

    A message without images stays a plain string, so a call without images
    sends exactly what it sent before PAGE_IMAGES_TO_MODEL.
    """
    out: List[Dict[str, Any]] = []
    for m in messages:
        images = m.get("images")
        if not images:
            out.append(text_messages([m])[0])
            continue
        parts: List[Dict[str, Any]] = [{"type": "text", "text": m.get("content") or ""},
                                       {"type": "text", "text": INTRO}]
        for image in images:
            parts.append({"type": "text", "text": image["label"]})
            parts.append({"type": "image_url", "image_url": {"url": image["url"], "detail": image["detail"]}})
        out.append({k: v for k, v in m.items() if k not in ("images", "content")} | {"content": parts})
    return out


def base_url_from_env(env: Mapping[str, str]) -> Optional[str]:
    """Where the function fetches page images it doesn't have on disk; None for disk only.

    PAGE_IMAGES_BASE_URL when set. On Vercel the images are the deployment's own
    static files: its own URL when VERCEL_AUTOMATION_BYPASS_SECRET is set (a
    protected preview answers the function only with that secret), else the
    production domain, which is public (a preview without the secret then reads
    production's images of the same PDF pages; a page production lacks is left out).
    """
    explicit = env.get("PAGE_IMAGES_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    own = env.get("VERCEL_URL", "").strip()
    production = env.get("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
    if own and env.get("VERCEL_AUTOMATION_BYPASS_SECRET", "").strip():
        return f"https://{own}"
    if production:
        return f"https://{production}"
    return f"https://{own}" if own else None


def headers_from_env(env: Mapping[str, str], base_url: Optional[str]) -> Dict[str, str]:
    """The protection bypass header, only for the deployment's own URL (never sent anywhere else)."""
    secret = env.get("VERCEL_AUTOMATION_BYPASS_SECRET", "").strip()
    own = env.get("VERCEL_URL", "").strip()
    if secret and own and base_url == f"https://{own}":
        return {"x-vercel-protection-bypass": secret}
    return {}

