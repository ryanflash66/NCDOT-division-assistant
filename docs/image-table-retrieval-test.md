# Retrieval on image- and table-heavy pages (DAR-651)

On Oct 29 Dr. Namian reported answers that cite the right document but the wrong page
(his example: page 37). We tested 15 questions with known answers that sit in a table, a
figure or a scanned page, on the current index and with two OCR extractors.

Measured on 2026-11-04 on the development machine (16 logical CPUs, Windows 11). The
questions are in `eval/image_table_questions.json`; the raw results are in
`docs/image-table-retrieval/*.json`. Rerun everything with the commands in
[How to rerun](#how-to-rerun).

## Summary

| | Current index | pymupdf4llm + OCR + captions | Docling + OCR |
|---|---|---|---|
| Right document in the top 5 | 13 / 15 | 15 / 15 | 15 / 15 |
| Right page in the top 5 | **4 / 15** | **14 / 15** | **13 / 15** |
| Right page ranked first | 3 / 15 | 13 / 15 | 13 / 15 |
| Full answers with the right value | 4 / 15 | 13 / 15 | 13 / 15 (2 with the wrong unit) |
| Full answers citing the expected page | 3 / 15 | 12 / 15 | 12 / 15 |
| Refusals | 6 | 0 | 0 |
| Extraction time, re-read pages | 0.4 s/page (no OCR) | 1.9 s/page | 2.7 s/page (3.1 median) |
| Extra dependencies for the index build | none | rapidocr, onnxruntime | docling (PyTorch, about 3 GB RAM) |

Main findings:

- **The page-37 case is a table split from its caption, not missing text.** The TMP manual's
  asphalt (p. 37) and concrete (p. 38) deflection tables differ only in their numbers and a
  caption that ends up in a chunk of its own. The current app answers the concrete question
  with the asphalt value. Keeping the caption in the table's chunks fixes it.
- **184 pages in 15 documents have no searchable text at all** (scanned attachments, pages
  that are pictures of text, drawings). Questions about them find the right document from
  neighbouring pages, then the wrong page or a refusal. OCR on just those pages fixes 9 of
  the 10 scan and figure questions in search.
- **Recommendation: pymupdf4llm with RapidOCR, plus captions carried into table chunks.**
  Same results as Docling at about 70% of its time per page, spent only on the pages that
  need OCR, and it keeps the current reader, so pages that already read well don't change. Details in [Recommendation](#recommendation).

## What the page-37 case was

It is the TMP Design Manual's NC-PCB deflection tables, and the cause is not OCR. Page 37
(Figure 4, **asphalt** pavement) and page 38 (Figure 5, **concrete** pavement) are the same
table layout with the same impact angles; only the deflections and the caption under each
table differ. The reader extracts both tables as text, but the splitter puts each caption
in a chunk of its own, so the chunks holding the numbers never say "asphalt" or "concrete".
Asked about concrete, the current app retrieves page 37 and answers with the asphalt value:

| Question | Right answer | Current app |
|---|---|---|
| Maximum deflection, NC-PCB on **concrete**, 20 ft offset, 60 mph | 25.37 in (p. 38) | 35.89 in, citing p. 37 (the asphalt value); on a second run 35.89 in uncited |

The same thing can happen to any table whose title sits apart from its rows (multi-page
tables with a repeated header, such as the Roadway Design Manual's Table 3 over pages
19-22). Carrying each page's figure/table caption into every chunk of that page
("+captions" below) fixes both deflection questions.

## Which pages the index cannot see

`python -m prototype.image_table_check pages` lists pages where the index holds under 50
characters but the PDF page has images or vector drawings: **184 pages in 15 of the 58
documents**. Text on them is invisible to the search, so no question about them can find
the page.

| Division | Document | Pages with no indexed text |
|---|---|---|
| utilities | 010604.pdf (FHWA utility relocation and accommodation guide) | 96 (chapters 10-12 and the sample permits are scans) |
| utilities | 20220713 NCDOT UAM Ver 2-0.pdf | 26 (the scanned attachments: 1999 effluent memo, frac-out plan) |
| wztc | Chapter_2.pdf (MUTCG flagging) | 22 (pages are images of text) |
| wztc | Chapter_5.pdf (MUTCG work operations) | 14 |
| tmsd | Signal System Timing Philosophy Manual.pdf | 6 (section title pages) |
| utilities | UtilitiesCoordination-Encroachments-presentation-notes.pdf | 4 |
| wztc | wzi_guide.pdf | 3 |
| tmsd | 03. Guardrail, Barriers and Attenuators.pdf | 3 (rotated detail drawings) |
| tmsd | TODS Manual - September 2024.pdf | 2 (MUTCD figures) |
| tmsd | 01102.pdf, 04091.pdf | 2 each |
| utilities, tmsd | utility_row.pdf, interim-design-safety-pilot-program.pdf, fhwa_hop_08_024.pdf, STEP-guide-improving-ped-safety.pdf | 1 each |

## The 15 questions

Five per division, each checked against the page image. Kinds: **table** = the reader
extracts the table, but split or apart from its caption; **figure** = text inside a
drawing; **scan** = a page that is a picture of text.

| ID | Kind | Document, page | Question (short) | Known answer |
|---|---|---|---|---|
| wztc-pcb-concrete | table | TMP Design Manual p. 38 | NC-PCB deflection, concrete, 20 ft, 60 mph | 25.37 in |
| wztc-pcb-asphalt | table | TMP Design Manual p. 37 | NC-PCB deflection, asphalt, 44 ft, 70 mph | 44.53 in |
| wztc-uneven-lanes | scan | Chapter_5 (MUTCG) p. 4 | Max elevation difference between open lanes, 30 mph+ | 2 in |
| wztc-curb-gutter | scan | Chapter_5 (MUTCG) p. 8, 10 | Curb and gutter: when to close the lane | within 2 ft, RSD 1101.02 |
| wztc-tma-weight | scan | Chapter_2 (MUTCG) p. 40 | Truck + TMA weight, who checks ballast | 10,000-20,000 lb, QWZS |
| utilities-fracout-depth | scan | UAM p. 300 | Frac-out at surface: removal depth | 2 ft |
| utilities-effluent-moa | scan | UAM p. 244, 250 | Date of the NCDOT-DENR effluent MOA | Jan 25, 1999 |
| utilities-sign-spacing | scan | 010604 p. 230 | Advance warning sign spacing, freeway | 1,000 / 1,600 / 2,600 ft |
| utilities-15ft-light | scan | 010604 p. 228 | Work 15 ft or more from the road: what control | flashing/revolving yellow light only |
| utilities-low-speed-layout | scan | 010604 p. 229 | Where the short 200 ft layout may be used | low-volume, 35 mph or less, not rural |
| tmsd-guardrail-l1 | figure | Guardrail (RDM 3) p. 12 | L1 on the trailing end of a rigid obstacle | N + 0.75 + lane width |
| tmsd-tods-placement | figure | TODS Manual p. 40 | TODS approach and advance sign placement | 200 ft min; advance 500 ft min |
| tmsd-tods-county | table | TODS Manual p. 24 | Onslow County code and division | 067, Division 3 |
| tmsd-turn-radius | table | At Grade Intersections p. 21 | 120 degree turn, SU-40 | 35 ft radius, 6.0 ft offset, 8:1 |
| tmsd-water-barrier | table | Guardrail (RDM 3) p. 4 | Barrier for a stream in the clear zone | yes if more than 2 ft deep |

## Search results (right page in the app's top 5)

The hosted app's retrieval (vector top 40 within the division, cross-encoder rerank, top 5),
`prototype.image_table_check search`. Each option re-reads the same 189 pages (the 184
low-text pages plus the table questions' pages) and replaces only those pages' chunks in a
copy of the committed index, split and embedded as `prototype.ingest` does. "#n" is the rank
of the first chunk from an expected page; "doc only" means the right document but not the
page in the top 5. "+captions" starts every chunk of a page with that page's figure/table captions.

| ID | Kind | Page | Current | Current + captions | pymupdf4llm + OCR | + captions | Docling + OCR | + captions |
|---|---|---|---|---|---|---|---|---|
| wztc-pcb-concrete | table | 38 | doc only | #1 | doc only | #1 | #1 | #1 |
| wztc-pcb-asphalt | table | 37 | #2 | #1 | #2 | #1 | #1 | #1 |
| wztc-uneven-lanes | scan | 4 | miss | miss | #1 | #1 | #1 | #1 |
| wztc-curb-gutter | scan | 8, 10 | miss | miss | #1 | #1 | #1 | #1 |
| wztc-tma-weight | scan | 40 | doc only | doc only | #1 | #1 | #1 | #1 |
| utilities-fracout-depth | scan | 300 | doc only | doc only | #1 | #1 | #1 | #1 |
| utilities-effluent-moa | scan | 244, 250 | doc only | doc only | #1 | #1 | #1 | #1 |
| utilities-sign-spacing | scan | 230 | doc only | doc only | #1 | #1 | #1 | #1 |
| utilities-15ft-light | scan | 228 | doc only | doc only | #1 | #1 | #1 | #1 |
| utilities-low-speed-layout | scan | 229 | doc only | doc only | #1 | #1 | #1 | #1 |
| tmsd-guardrail-l1 | figure | 12 | doc only | doc only | doc only | doc only | doc only | doc only |
| tmsd-tods-placement | figure | 40 | doc only | doc only | #1 | #1 | doc only | doc only |
| tmsd-tods-county | table | 24 | #1 | #2 | #2 | #2 | #1 | #1 |
| tmsd-turn-radius | table | 21 | #1 | #1 | #1 | #1 | #1 | #1 |
| tmsd-water-barrier | table | 4 | #1 | #1 | #1 | #1 | #1 | #1 |
| **Right page in top 5** | | | **4** | **5** | **13** | **14** | **13** | **13** |
| Right page first | | | 3 | 4 | 11 | 13 | 13 | 13 |
| Right document in top 5 | | | 13 | 13 | 15 | 15 | 15 | 15 |

Notes:

- Docling keeps each caption next to its table, so it ranks both deflection pages first
  without the caption step; pymupdf4llm needs it.
- The Guardrail detail (p. 12) is a drawing rotated 90 degrees. Both OCR runs read only part
  of it, and the formula's chunk doesn't rank in the top 5 (the full answer still found it with
  pymupdf4llm, through the passage merged from p. 9). Docling turned the TODS figure on p. 40
  into an image placeholder plus its three footnotes, while pymupdf4llm's OCR read the
  "200 ft MIN" and "500 ft MIN" labels.
- TODS county code drops from #1 to #2 whenever the page is re-read through pymupdf4llm on its
  own: with only a few pages, pymupdf4llm sizes headings differently than on the whole
  document. It still ranks second, and the answer is right in every run.

## Full answers

Each question through the app's `/api/ask` (free OpenRouter models, as deployed) on the current
index and on each OCR option's index with captions. Graded by hand against the known answer;
"cited" is whether a cited source covers the expected page.

| ID | Current | pymupdf4llm + OCR + captions | Docling + OCR + captions |
|---|---|---|---|
| wztc-pcb-concrete | **wrong**: 35.89 in (the asphalt value), uncited; p. 37 on an earlier run | right, 25.37 in, cited p. 38 | right value, says "ft", cited p. 38 |
| wztc-pcb-asphalt | wrong: 31.30 in, uncited | **wrong**: 42.89 in, cited p. 37 | right value, says "ft", cited p. 37 |
| wztc-uneven-lanes | refused | right, cited p. 4 | right, uncited |
| wztc-curb-gutter | refused | right, cited p. 7-10 | right, cited p. 8-11 |
| wztc-tma-weight | wrong: quotes the Standard Specifications (p. 621) | right, cited p. 40 | right, cited p. 40 |
| utilities-fracout-depth | refused | right, uncited | right, cited p. 300 |
| utilities-effluent-moa | right, uncited | right, uncited | right, cited p. 244 |
| utilities-sign-spacing | refused (suggested other divisions) | right, cited p. 230 | right, cited p. 230 |
| utilities-15ft-light | refused | right, cited p. 228 | right, cited p. 228 |
| utilities-low-speed-layout | refused | right, cited p. 228-229 | right, cited p. 228-229 |
| tmsd-guardrail-l1 | wrong: "the passages do not specify" | right, cited p. 9-12 | wrong: "the passages do not specify", uncited |
| tmsd-tods-placement | partly: 200 ft right, advance signs missing; cited p. 7, 25 | partly, cited p. 25 | partly, cited p. 25 |
| tmsd-tods-county | right, cited p. 23-24 | right, cited p. 23-24 | right, cited p. 23-24 |
| tmsd-turn-radius | right, cited p. 20-21 | right, cited p. 20-22 | right, cited p. 21-22 |
| tmsd-water-barrier | right, cited p. 4 | right, cited p. 4 | right, cited p. 4 |
| **Right value** | **4** (+1 partly) | **13** (+1 partly) | **13** (+1 partly) |
| **Cites the expected page** | 3 | 12 | 12 |
| **Refused** | 6 | 0 | 0 |
| Median answer time | 3.5 s | 2.5 s | 2.6 s |

Two answers are still wrong in a way OCR can't fix. On the asphalt question with pymupdf4llm
the model read a neighbouring row (42.89 is the 50 ft / 60 mph cell): the table's vertical
"Offset (ft)" header splits into the row labels, and the second half of the table comes in a
chunk whose header is garbled. Docling reads the same table cleanly, with the caption on top
and "Maximum Deflection (in)" in the header row, yet the model still wrote "ft" for both
deflection answers. Tables like these need a clean header in every chunk, and the unit
error is a prompt or model issue rather than an extraction one.

The current app's answers vary between runs: the concrete question cited page 37 on the
first run and nothing on the second, with the same wrong value both times.

## Extraction time

Re-reading the same 189 pages, per page (one document at a time, model loading excluded):

| Option | Total | Mean | Median | Pages still under 50 characters |
|---|---|---|---|---|
| pymupdf4llm, no OCR (current reader) | 80 s | 0.4 s | 0.25 s | 184 |
| pymupdf4llm + RapidOCR (200 dpi) | 367 s | 1.9 s | 2.0 s | 18 (blank or photo pages) |
| Docling + RapidOCR, table structure on | 638 s | 2.7 s (without its first-run model download) | 3.1 s | 25 |

The Docling run shared the CPU with an answers run for part of the time, so read its time as
an upper bound. pymupdf4llm only OCRs pages it judges need it, so on a full rebuild the extra
time falls on those pages: at 1.9 s each, the 184 pages found here add about 6 minutes to a
build that takes about 55 (docs/stress-test-50-documents.md). Docling would replace the reader
for every page: about 5,900 pages at 2.7 s is roughly 4.5 hours.

## Recommendation

**Adopt pymupdf4llm with RapidOCR, and carry each page's figure/table captions into its chunks.**

- It matches Docling on these 15 questions (right page in the top 5: 14 vs 13; right answers:
  13 vs 13) at about 70% of the time per page, and only on the pages that need OCR.
- It is the reader the index already uses, so the 5,700 pages that read well today come out
  the same and keep their chunks; Docling would change every page's Markdown and need the
  whole index re-checked (eval/retrieval_pages.json, the table questions).
- Its dependencies are small (rapidocr, onnxruntime) and stay in the offline build: the hosted
  app is unaffected. Docling brings PyTorch and about 3 GB of memory into the build.
- The caption step is what fixes the page-37 case, and it is a few lines in `prototype.ingest`.

For the rebuild ticket (out of scope here):

- Install the OCR engine only in the environment that runs `prototype.ingest`, and pass
  `use_ocr=True` with an explicit `ocr_function` in `rag.loader`. pymupdf4llm turns OCR on by
  itself whenever an engine is importable, so make it explicit rather than depend on what is installed.
- `010604.pdf` pages 226-227 already carry a poor OCR text layer ("trafK!ic"). pymupdf4llm
  keeps existing OCR by default; consider forcing OCR for that document.
- Rerun `eval/retrieval_pages.json`, the table questions and this test after the rebuild.
- Still not covered: the rotated Guardrail detail drawings, and multi-page tables whose
  header gets garbled. Vision-model page retrieval (e.g. ColPali) is the direction for those;
  it is noted for the literature review (DAR-624).

## How to rerun

The OCR extractors run in their own virtual environment, because pymupdf4llm turns OCR on by
itself as soon as an OCR engine is importable: installing RapidOCR into `.venv` would change
what `prototype.ingest` builds.

```bash
py -3.13 -m venv .venv-ocr
.venv-ocr\Scripts\python -m pip install "pymupdf4llm==1.28.2" "pymupdf-layout==1.28.2" rapidocr onnxruntime docling
.venv\Scripts\python -m prototype.image_table_check pages --out results\pages.json
.venv\Scripts\python prototype\ocr_extract.py --option pymupdf4llm --pages results\pages.json --out results\ext-pymupdf4llm.json
.venv-ocr\Scripts\python prototype\ocr_extract.py --option pymupdf4llm-ocr --pages results\pages.json --out results\ext-pymupdf4llm-ocr.json
.venv-ocr\Scripts\python prototype\ocr_extract.py --option docling-ocr --pages results\pages.json --out results\ext-docling-ocr.json
.venv\Scripts\python -m prototype.image_table_check search --option current+captions=results\ext-pymupdf4llm.json --option pymupdf4llm-ocr=results\ext-pymupdf4llm-ocr.json --option pymupdf4llm-ocr+captions=results\ext-pymupdf4llm-ocr.json --option docling-ocr=results\ext-docling-ocr.json --save-index pymupdf4llm-ocr+captions=results\index-ocr --out docs\image-table-retrieval\search.json
```

For the full answers, start the app on an index (`INDEX_DIR=results\index-ocr`, and
`RATE_LIMIT_PER_MINUTE=1000` so the 15 questions aren't throttled) and run
`.venv\Scripts\python -m prototype.image_table_check answers --base-url http://127.0.0.1:8000 --label NAME --out docs\image-table-retrieval\answers-NAME.json`.
Each run is 15 or more calls to the free models, which share a daily cap.
