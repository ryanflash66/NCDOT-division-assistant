# Two readings of picture pages: cost estimate (DAR-739)

Nov 23, 2026. Estimate only: no OpenAI call was made. From `py -m prototype.read_pages --estimate` on the committed index (Nov 18).

## Short version

| | |
|---|---|
| Pages to read | **1,192** of the index's 5,797 |
| Model | `gpt-6.1-terra`, $1 / $5 per million tokens in / out (`hosted/divrag/spend.py`), reasoning effort none |
| Image | 100 dpi grayscale JPEG, detail `high` (850 x 1100 for a letter page; largest 1325 x 2048) |
| **Cost, one run over every page** | **about $8.80** (range $5.40 to $12.10) |
| Cost at answer time | none: the readings are read once and stored beside the index |
| Month so far | $7.16 of the $45 switch (after DAR-650), so about $16 after the run |

## Which pages

The pages whose text in the index came out of a picture, as `page_images.reasons()` names them (first reason):

| Reason | Pages |
|---|---|
| scan (no text layer, read by OCR) | 186 |
| rotated (OCR turned the page, or its text runs sideways) | 123 |
| picture (a drawing's picture text) | 777 |
| figure (a figure caption's own chunk) | 106 |
| **Total** | **1,192** |

Tables and captioned pages whose text came from the PDF's text layer are not read: that text is the printed text. The five DAR-732 pages are all in the set (utilities-h056 010604.pdf p.278 scan; tmsd-h009 TODS p.39 scan; tmsd-h049 Guardrail p.3 picture; tmsd-h052 At Grade Intersections p.13 rotated; tmsd-h019 Policy on Access p.88 rotated).

## How the cost is figured

| | Tokens | Cost |
|---|---|---|
| Input at DAR-733's measured image rate (about 1,300 tokens a 510 x 660 page, scaled by area), plus 450 of prompt a page | 5.56 M | $5.56 |
| Input by OpenAI's published patch count instead (1.2 a 32 px patch), the low end | 2.11 M | $2.11 |
| Output: the page's OCR text length / 4 x 1.3 for the Markdown | 0.65 M | $3.25 |
| **Total**, measured rate | | **$8.82** |
| Total, patch count | | $5.36 |
| Total, measured rate with twice the output | | $12.07 |

The measured rate is the one to trust: DAR-733's logs showed images billed at about three times the patch count. The first few pages of the run report their real `usage`, so the estimate is checked before the rest go (the run stops at `--max-usd`).

Time: 4 calls at a time, about 10 to 20 s a page, so roughly an hour for the whole set.

## The plan for the run

1. Read the five DAR-732 pages first (`--page ...`, a few cents) and look at their readings and flags.
2. Read the rest with `--max-usd 15`.
3. Commit `hosted/index/page_readings.json` and the flag counts, and run the held-out set (286) with `PAGE_READINGS` on against DAR-738.
