# Page images to the model: cost estimate (DAR-733)

Nov 17, 2026. Estimate only: no OpenAI or OpenRouter call was made. The counts come from running the held-out set's retrieval (no language model) on the local index at this branch, with the site's default settings (TOP_K 5, rerank on, keyword search on), and applying the new rule for which pages get an image (`hosted/divrag/page_images.py`).

## Short version

| | Today (text only) | With `PAGE_IMAGES_TO_MODEL=on` (cap 4 a call) |
|---|---|---|
| One question, first model call | about $0.0031 | **+ $0.00065** (about +21%) |
| One held-out run (286 questions) | about $0.90 (measured, Nov 16) | **about $1.15** (+ $0.24; at most about $1.45) |
| Questions per month inside the $45 switch (DAR-715) | about 14,500 | about 11,500 |

## What an image costs

- Model: `gpt-6.1-terra`, $1 per million input tokens, $5 per million output (OpenAI model page, read Nov 17, 2026; the same prices are in `hosted/divrag/spend.py`). The model page lists image input and no separate image price: images are billed as input tokens.
- The images sent are the existing Sources-panel renders (DAR-654/665): 60 dpi grayscale JPEG, 510 x 660 px for a letter page, about 43 KB. Nothing new is rendered.
- Tokens per image: OpenAI's vision guide (read Nov 17, 2026) bills the current models by 32 x 32 px patches times a multiplier of 1.2 (every current model it lists: gpt-5.2 to gpt-5.6, gpt-6-astra). 510 x 660 is 16 x 21 = 336 patches, **404 tokens**, at `detail` `auto`, `high` or `original` (no resizing at that size). `low` fits the image in 512 x 512: 13 x 16 patches, 250 tokens, but the small print of a scanned table blurs, so the default is `auto`.
- Assumption: `gpt-6.1-terra` is not in the guide's table. If it were billed like gpt-4.1-mini (1.62 a patch) an image would be 544 tokens; tile-based like gpt-5.1 (70 + 140 a tile, 2 tiles) it would be 350. The range is 350 to 544 tokens, $0.00035 to $0.00054 an image. The real count shows in the first preview run: the call's `usage.prompt_tokens` includes the images, and the monthly ledger (`openai_spend` log lines) counts them.

## How many images a question carries

Counted over the 286 held-out (locked split) questions, on the passages the first model call reads (top 5 plus the following chunk of the top 2, merged):

| Qualifying pages a question has | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| Questions | 89 | 56 | 59 | 39 | 25 | 12 | 5 | 1 |

- 197 of 286 questions (69%) would send at least one image. Mean 1.71 qualifying pages a question, at most 7.
- Each page counted once, under its first reason in this order: table 159, picture text 154, no text layer (scan) 68, figure/table caption 67, sideways 31, figure caption chunk 9.
- With the default cap of 4 images a call: 463 images over the 286 questions, **1.62 a question, 654 tokens, $0.00065**. A cap of 3 gives 420 (1.47 a question), 2 gives 338, 1 gives 197; 5 or more adds almost nothing (481 to 488). The cap keeps the scans, sideways pages and picture pages first, then the best-ranked.
- Text prompt for comparison: about 3,200 tokens a question by character count (4 characters a token), so images add about a fifth to the input.

## One held-out run

| Part | Images | Tokens | Cost |
|---|---|---|---|
| First call, 286 questions | 463 | 187,000 | $0.19 |
| Retry after a refusal (about 26 questions, as in the Nov 16 run): the first call's images again (1.62) and the second look's own (mean 2.92 of the cap of 4) | about 120 | about 48,000 | $0.05 |
| Recite and number recheck (resend the first call's images; the Nov 16 run had 1 uncited answer and no unverified number) | a few | | under $0.01 |
| **Extra for the run** | | | **about $0.24** |

So one run costs about **$1.15 instead of $0.90**. Bounds: at 544 tokens an image, about $0.32 extra ($1.22); if every call carried the full 4 images (and every retry 4 more), $0.55 extra ($1.45). Either way a run stays under 3% of the $45 monthly switch.

The baseline is the site's own estimate for the Nov 16 run (`docs/heldout-set/openai-site-main.md`: "about $0.90", 286 questions, 260 answered by gpt-6.1-terra and 26 refused by it then retried; retries now go to OpenAI too, PR #64).

## Time

- Images are fetched from the deployment's CDN in parallel before the first model call, at most 3 s (`FETCH_TIMEOUT_SECONDS`; then the call goes text-only), and kept in the instance's memory (256 pages, about 11 MB), so a page already sent costs nothing.
- Base64 of 4 x 43 KB is about 230 KB of request body, under OpenAI's limits.
- How much the images slow OpenAI's first token is not measured; the preview run's `timing_ms.llm` against the Nov 16 run's will show it.

## The five DAR-732 pages

All five gold pages qualify, and four of them reach the first call within the cap:

| Item | Gold page | Reason | In the first call's passages | Image position (cap 4) |
|---|---|---|---|---|
| utilities-h056 | 010604.pdf p.278 | no text layer | yes | 1st |
| tmsd-h009 | TODS Manual p.39 | no text layer | yes | 1st |
| tmsd-h049 | Guardrail chapter p.3 | picture text | yes | 3rd |
| tmsd-h052 | Chapter 9 p.13 | sideways | yes | 1st |
| tmsd-h019 | Policy on Access p.88 | sideways | no: only in the second look after a refusal | 2nd of the second look |

Rendered at the site's 60 dpi, the five pages are legible: the "1 ½ inches" on the scanned Indiana permit, the sideways turn-lane tables (150 ft bay taper at 55 mph; 300 ft desirable deceleration at 50 mph) and the "2 ½" on the TODS sign. tmsd-h019 still depends on the retry after a refusal reaching that page (OpenAI declined it on Nov 16 without having seen it).

Note: these five items were read in detail for DAR-732, so they are development items now, as that report says; they are a check here, not a measurement.

## Sources

- OpenAI, gpt-6.1-terra model page (developers.openai.com/api/docs/models/gpt-6.1-terra): input modalities text and image; $1 / $5 per million tokens.
- OpenAI, Images and vision guide (developers.openai.com/api/docs/guides/images-vision): patch size, multipliers, detail levels.
- OpenAI, Chat Completions reference: `image_url` content part with `url` (an https URL or a base64 data URL) and `detail` (`auto`, `low`, `high`, `original`).
- Counts: retrieval of `evaluation/heldout/{wztc,utilities,tmsd}.json` (split `locked`) on `hosted/index` at this branch; page images per `page_images.wanted_pages`, limited to the pages `render_pages.py --only-indexed` renders.
