"""Render each division's PDF pages to small grayscale JPEGs for the Sources panel (DAR-654).

    python hosted/scripts/render_pages.py [--division ID ...] [--file NAME ...] [--out hosted/public/pages]
                                          [--dpi 60] [--quality 60] [--only-indexed hosted/index/chunks.json]
                                          [--force]

Each page goes to <out>/<division>/<slug>/<page>.jpg, the path divrag.pages_static
gives it, and a manifest of what was rendered is written beside the folder
(<out>/../page-images.json) for the app, which on Vercel can't see the folder
(vercel.json leaves it out of the function bundle; the CDN serves it). The
manifest is rebuilt from the whole folder after every run, so partial renders
(one division, --only-indexed) add up.

--only-indexed renders only the pages that have a passage in the index, which
is what a citation can point at. A page already rendered is skipped unless
--force. It prints each document's pages and bytes and the totals, so the size
of a setting can be measured: 60 dpi at JPEG quality 60 reads well enough to
check a table's row and is about 43 KB a page.

This is a build-time tool (Vercel runs it when RENDER_PAGES=1, see README),
not part of the app: pymupdf is not a runtime dependency. From the repo root,
`py -m prototype.render_pages` runs the same thing.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

HOSTED_DIR = Path(__file__).resolve().parent.parent
if str(HOSTED_DIR) not in sys.path:
    sys.path.insert(0, str(HOSTED_DIR))

from divrag.divisions import BY_ID, DIVISIONS, DOCUMENTS_DIR, Division, Document  # noqa: E402
from divrag.pages_static import PAGES_DIR, slug, write_manifest  # noqa: E402

# 60 dpi makes a letter page 510 x 660 px: a table's numbers are readable at
# the panel's width. Measured on 300 random indexed pages: 43 KB a page, about
# 250 MB for the 5,822 indexed pages; 50 dpi/quality 50 is 27 KB (160 MB), a
# third smaller, but the smaller table text starts to smear.
DEFAULT_DPI = 60
DEFAULT_QUALITY = 60


def indexed_pages(chunks_file: Path) -> Dict[Tuple[str, str], Set[int]]:
    """The PDF pages with at least one chunk, per (division, document file name), from chunks.json.

    Keyed by division too, because the images are stored per division: a file
    listed by two divisions only gets the pages each division indexed.
    """
    data = json.loads(chunks_file.read_text(encoding="utf-8"))
    pages: Dict[Tuple[str, str], Set[int]] = {}
    for chunk in data["chunks"] if isinstance(data, dict) else data:
        if chunk.get("division") and chunk.get("source") and chunk.get("page"):
            pages.setdefault((chunk["division"], chunk["source"]), set()).add(int(chunk["page"]))
    return pages


def document_path(division: Division, document: Document, documents_dir: Path) -> Optional[Path]:
    path = documents_dir / division.id / document.file
    return path if path.is_file() else None


def render_document(pdf: Path, out_dir: Path, dpi: int, quality: int, pages: Optional[Set[int]] = None,
                    force: bool = False) -> List[int]:
    """Render the document's pages (all, or `pages`) into out_dir; the sizes in bytes of the files written."""
    import pymupdf  # imported here: only the render needs it, and the app must not

    sizes: List[int] = []
    if pages is not None and not pages:
        return sizes
    out_dir.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as doc:
        # Only the wanted pages are loaded: on Vercel nothing is cached between
        # builds, so every build renders from scratch.
        numbers = sorted(n for n in pages if 1 <= n <= doc.page_count) if pages is not None             else range(1, doc.page_count + 1)
        for number in numbers:
            target = out_dir / f"{number}.jpg"
            if target.exists() and not force:
                continue
            # Written under another name and renamed, so a failed save never leaves
            # a truncated .jpg that a later run would skip and the manifest list.
            partial = out_dir / f"{number}.jpg.part"
            try:
                pix = doc.load_page(number - 1).get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
                partial.write_bytes(pix.tobytes("jpg", jpg_quality=quality))
                partial.replace(target)
            except Exception as exc:  # a broken page shouldn't stop the document
                partial.unlink(missing_ok=True)
                print(f"    page {number}: not rendered ({exc.__class__.__name__}: {exc})", file=sys.stderr)
                continue
            sizes.append(target.stat().st_size)
    return sizes


def folder_size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*.jpg"))


def run(divisions: Sequence[Division], out: Path, dpi: int, quality: int,
        only: Optional[Dict[Tuple[str, str], Set[int]]],
        files: Optional[Iterable[str]], documents_dir: Path, force: bool) -> int:
    """Render the selected documents and write the manifest; the exit code (1 if a PDF was missing)."""
    wanted = set(files) if files else None
    missing = 0
    started = time.monotonic()
    for division in divisions:
        for document in division.documents:
            if wanted is not None and document.file not in wanted:
                continue
            pdf = document_path(division, document, documents_dir)
            if pdf is None:
                print(f"{division.id}: {document.file}: not in {documents_dir / division.id}, skipped", file=sys.stderr)
                missing += 1
                continue
            pages = only.get((division.id, document.file), set()) if only is not None else None
            folder = out / division.id / slug(document.file)
            sizes = render_document(pdf, folder, dpi, quality, pages, force)
            count = len(list(folder.glob("*.jpg")))
            print(f"{division.id}: {document.file} -> {folder.relative_to(out)}: "
                  f"{len(sizes)} rendered, {count} pages, {folder_size(folder) / 1e6:.1f} MB")
    rendered = write_manifest(out, out.parent / "page-images.json")
    total_files = sum(len(pages) for pages in rendered.values())
    print(f"total: {total_files} files, {folder_size(out) / 1e6:.1f} MB ({folder_size(out):,} bytes) "
          f"at {dpi} dpi, quality {quality}, in {time.monotonic() - started:.0f} s; "
          f"manifest {out.parent / 'page-images.json'}")
    return 1 if missing else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--division", action="append", choices=[d.id for d in DIVISIONS],
                        help="render only this division's documents (repeatable)")
    parser.add_argument("--file", action="append", help="render only this document file name (repeatable)")
    parser.add_argument("--out", type=Path, default=PAGES_DIR, help=f"folder for the images (default {PAGES_DIR})")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--quality", type=int, default=DEFAULT_QUALITY, help="JPEG quality 1-100")
    parser.add_argument("--only-indexed", type=Path, metavar="CHUNKS_JSON",
                        help="render only the pages that have a passage in this index")
    parser.add_argument("--documents", type=Path, default=DOCUMENTS_DIR,
                        help=f"where the PDFs are, one folder per division (default {DOCUMENTS_DIR})")
    parser.add_argument("--force", action="store_true", help="render pages that already have an image")
    args = parser.parse_args(argv)
    divisions = [BY_ID[d] for d in args.division] if args.division else list(DIVISIONS)
    only = indexed_pages(args.only_indexed) if args.only_indexed else None
    return run(divisions, args.out, args.dpi, args.quality, only, args.file, args.documents, args.force)


if __name__ == "__main__":
    sys.exit(main())
