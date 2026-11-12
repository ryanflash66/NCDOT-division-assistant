# DAR-665. Page images in the production build

**What changed.** The build can now put the cited page's image on the live site, as static files, without touching the Python function. It is still off until `RENDER_PAGES=1` is set in Vercel (see "What is left"). Decision D3 in `docs/redo-decision-log.md` left this open.

## Sizes (measured, not estimated)

All numbers are from rendering the real PDFs in `hosted/documents/` with `hosted/scripts/render_pages.py` (60 dpi, grayscale JPEG, quality 60) for every page that has a chunk in `hosted/index/chunks.json`.

| | Count / bytes |
|---|---|
| Documents (58, no file shared between divisions) | wztc 20, tmsd 20, utilities 18 |
| Pages that can be cited (division, page pairs with a chunk) | 5,797 (wztc 2,451, tmsd 2,287, utilities 1,059) |
| All pages of the 58 PDFs | 5,910 |
| The PDFs the build has to download | 247.9 MB |
| Images at 60 dpi, quality 60 | 247,545,175 bytes (247.5 MB), 42.7 KB a page |
| Render time, one process, 16-core workstation | 392 s for everything (44 s for utilities' 1,059 pages) |

Sample of 20 pages (one random indexed page from 20 random documents, seed 665), average per page:

| Setting | KB | ms to render and encode |
|---|---|---|
| JPEG 60 dpi q60 (current) | 39.3 | 32 |
| JPEG 50 dpi q50 | 24.4 | 16 |
| JPEG 72 dpi q60 | 54.5 | 29 |
| WebP 60 dpi q60 | 33.4 | 92 |
| WebP 72 dpi q50 | 42.6 | 100 |
| WebP 72 dpi q40 | 39.4 | 101 |
| WebP 90 dpi q50 | 61.1 | 155 |

## Choice: keep JPEG, 60 dpi, quality 60, only pages with chunks

- **Legibility.** TMP Design Manual PDF p.37 (the dense impact-angle table) is readable at 60 dpi: every number in the table can be read. A text page (Signal System Timing Philosophy Manual p.51) is also clear. At 50 dpi the table digits start to smear (README note from DAR-654, same finding here).
- **WebP is not worth it.** At the same dimensions it saves about 15% (33 against 39 KB) but takes three times longer to encode, and `pymupdf` cannot write WebP itself, so the build would also need Pillow. At equal size it is no more legible.
- **Only indexed pages.** 5,797 of 5,910 pages, so only 113 pages (2%) are skipped. This is not a saving worth more than the rule that a citation can only point at an indexed page.
- **Lower DPI** saves 38% (150 MB) but costs legibility on tables, the reason the images exist. Not chosen.

## Does Vercel allow it

From Vercel's documentation (docs.vercel.com `/docs/limits` and `/docs/builds`, read through the Vercel docs tool):

- **Static output size.** "There is no upper limit for output files created during a build"; many thousands of files only lengthen the build. The 15,000-file limit applies to source files uploaded with the CLI, not to files a build creates. We have 5,797 image files plus the page.
- **Build time.** The build step may last 45 minutes. The extra work is the document download (248 MB) plus about 6.5 minutes of rendering measured here (a Hobby build machine has 2 vCPUs, so allow 5 to 10 minutes). The web build and model fetch were already part of the build.
- **Build disk.** 32 GB; PDFs plus images are about 0.5 GB.
- **Function bundle.** Files under `public/` are served by the CDN. `vercel.json` already excludes `public/pages/**` and `documents/**` from the Python function, which keeps the 500 MB function limit out of this.
- **No paid service is needed**, so Vercel Blob was not looked at further.

## Function bundle before and after

Files matched by the function's `includeFiles` (`public/**`) minus `excludeFiles`, plus the project files, from `vercel.json`'s patterns applied to the real tree (the dependencies and the ONNX models, about 300 MB, are not changed by this work):

| | Files | Bytes |
|---|---|---|
| Before (no images) | 34 | 38.20 MB |
| After (all 5,797 images rendered) | 35 | 38.23 MB |
| After, if `excludeFiles` did not exclude `public/pages/**` and `documents/**` | 5,921 | 286.57 MB |

The only new file in the function is `public/page-images.json` (22 KB, the list of pages that have an image, which the function needs to set `image` on a source). `tests/test_hosted_build_script.py` checks that `vercel.json` keeps `public/pages/**` and `documents/**` excluded.

## Changes

- `hosted/scripts/build.sh`: pymupdf is installed with `--target` into a temporary folder, not the build's Python environment. The function bundle is built from that environment and must not pick up a render-only package. If `pip` is missing there (Vercel's Python build uses `uv`), `uv pip install --target` is tried. Failure of any step still deploys without the images.
- `hosted/scripts/render_pages.py`: an unreadable PDF no longer stops the run before the manifest is written; it is reported and counted as missing.
- `hosted/web/src/panels/PageImage.tsx`: the image now fills the panel's width (up to 32 rem) instead of being capped at 18 rem high. The cap made a 660 px page 288 px tall, too small to read a table in. If the image fails to load, nothing is shown, as before.
- Tests: `tests/test_hosted_build_script.py` (the switch, pymupdf kept out of the environment, failure does not fail the build, the exclusions), a render test for an unreadable PDF, and a PageImage test for the removed height cap. Fallback tests (no image, failed load, bad URL) already existed.
- `README.md`: the measured sizes and the setting to turn it on.

## Checked locally

The utilities division (1,059 pages) was rendered into `hosted/public/pages/` with the build's script and the app run on port 8065. `/pages/utilities/hif22002/3.jpg` returned 200 `image/jpeg` (64 KB). A page and a document without an image returned 404 (the panel's fallback hides the image, so no broken icon). One question was asked in the browser (Utilities, "Who pays for a detour when a utility closes a road?", one model call): the source showed the image of UAM PDF page 127 with a link to the PDF at that page, 341 x 442 px at a 375 px wide window with no horizontal scroll, and the page image on the desktop layout.

## What is left for the live check

The production site is paused, so none of this ran on Vercel. After it is unpaused:

1. Set the Vercel environment variable `RENDER_PAGES` to `1` for the **Production** environment (Project Settings, Environment Variables), then redeploy. Previews only build when a commit's first line has `[preview]` (`hosted/scripts/ignore_build.sh`); to see images on a preview, set it for Preview too.
2. Read the build log: the lines starting `utilities:`, `wztc:`, `tmsd:` and `total: 5797 files`. Check the build time stays well under 45 minutes. Not known: whether `connect.ncdot.gov` serves all 58 PDFs to Vercel's build machines (`fetch_documents.py` is allowed to fail per file; a missing PDF only costs its images) and whether `pip` or `uv` is available in Vercel's Python build (the script tries both).
3. Open a source in the live app and check the image loads from `/pages/...` (CDN) and that the function size in the build log (set `VERCEL_ANALYZE_BUILD_OUTPUT=1` to list it) is still about 340 MB.
4. Images are cached with Vercel's default static headers; no cache-control rule was added. Not measured on the live site.
