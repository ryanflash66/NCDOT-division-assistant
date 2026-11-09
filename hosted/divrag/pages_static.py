"""Where a cited page's image lives, for the Sources panel (DAR-654).

A reader who gets a number out of a table wants to see the table, not a
700-character excerpt of it flattened to one line. scripts/render_pages.py
renders each PDF page to a small grayscale JPEG under public/pages/, and the
panel shows the cited page's image, linked to the PDF at that page.

The images are static files: on Vercel the CDN serves public/, and vercel.json
keeps public/pages/ out of the function bundle (the 5,822 indexed pages are about 250 MB,
and the bundle is already about 340 MB of its 500 MB limit). So the function
can't look for a page on disk: the render script writes a manifest beside the
folder (public/page-images.json, which the bundle does include) listing the
pages rendered per document, and image_url() reads that. Without the
manifest, a local checkout that rendered pages is read by scanning the folder;
without either, every source's image is None and the panel shows no image.

The path of a page is pages/<division>/<slug>/<page>.jpg, with slug() a
URL-safe version of the document's file name (the names have spaces, commas,
ampersands and dots: "2023 WZ Safety & Mobility Process Review.pdf"). Both
the render script and the app go through page_image_path(), so the two can't
drift. The prototype's render_pages wrapper imports this module from hosted/,
the way prototype.ingest imports divrag; hosted never imports prototype/.
"""

import json
import re
from pathlib import Path
from typing import Dict, Optional, Set

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
# The rendered pages, and the manifest the render script writes beside them.
PAGES_DIR = PUBLIC_DIR / "pages"
MANIFEST_FILE = PUBLIC_DIR / "page-images.json"
URL_PREFIX = "/pages"

_NOT_SLUG = re.compile(r"[^a-z0-9]+")
# "division/slug" -> the PDF pages rendered for it. None until first use.
_rendered: Optional[Dict[str, Set[int]]] = None


def slug(file: str) -> str:
    """A URL-safe, deterministic folder name for a document's file name.

    Lower case, runs of anything but letters and digits become one hyphen, and
    the .pdf extension goes: "TMP Design Manual (Combined, No Links).pdf" ->
    "tmp-design-manual-combined-no-links". A test checks the real file names
    stay distinct within their division, since the folder is per division.
    """
    stem = file[:-4] if file.lower().endswith(".pdf") else file
    return _NOT_SLUG.sub("-", stem.lower()).strip("-") or "document"


def page_image_path(division: str, file: str, page: int) -> str:
    """The page's image path relative to the pages folder: "<division>/<slug>/<page>.jpg"."""
    return f"{division}/{slug(file)}/{int(page)}.jpg"


def image_url(chunk: Dict) -> Optional[str]:
    """The site-relative URL of the chunk's page image, or None when it isn't rendered.

    A merged passage (page..page_end) shows its first page; the link under the
    image opens the PDF there, and the page can be turned from the PDF.
    """
    division, source, page = chunk.get("division"), chunk.get("source"), chunk.get("page")
    if not (division and source and page):
        return None
    if int(page) not in rendered().get(f"{division}/{slug(source)}", ()):
        return None
    return f"{URL_PREFIX}/{page_image_path(division, source, int(page))}"


def rendered() -> Dict[str, Set[int]]:
    """The pages that have an image, "<division>/<slug>" -> set of PDF pages; read once.

    From the manifest when there is one (the function bundle on Vercel), else
    from the folder itself (a local checkout after a render), else empty.
    """
    global _rendered
    if _rendered is None:
        _rendered = _read_manifest(MANIFEST_FILE) if MANIFEST_FILE.is_file() else scan(PAGES_DIR)
    return _rendered


def reset() -> None:
    """Forget the cached listing (tests). A render while the app runs shows after a restart."""
    global _rendered
    _rendered = None


def scan(pages_dir: Path) -> Dict[str, Set[int]]:
    """The rendered pages found under `pages_dir`, in the manifest's shape; empty when it is absent."""
    found: Dict[str, Set[int]] = {}
    if not pages_dir.is_dir():
        return found
    for image in pages_dir.glob("*/*/*.jpg"):
        if image.stem.isdigit():
            found.setdefault(f"{image.parent.parent.name}/{image.parent.name}", set()).add(int(image.stem))
    return found


def write_manifest(pages_dir: Path, manifest_file: Path) -> Dict[str, Set[int]]:
    """Write the manifest for what is under `pages_dir` and return it."""
    found = scan(pages_dir)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(
        json.dumps({key: sorted(pages) for key, pages in sorted(found.items())}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return found


def _read_manifest(manifest_file: Path) -> Dict[str, Set[int]]:
    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        return {str(key): {int(p) for p in pages} for key, pages in data.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        # A damaged manifest costs the images, never the answer.
        return {}
