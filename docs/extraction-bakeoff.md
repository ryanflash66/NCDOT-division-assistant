# Extraction bake-off on the 117 hardest pages (DAR-656)

**Recommendation: keep pymupdf4llm + RapidOCR as the reader for every page. Do not route pages to
Docling or MinerU.** Neither wins a class of pages. Both lose text that pymupdf4llm keeps, and both
are slower. The one failure all three tools share (rotated table headers such as "Offset (ft)") comes
from how the tools read rotated glyphs. The PDF's own text layer has those headers intact, so the fix
belongs in our table code (DAR-655 / U9), not in a different tool. A paid vision model would only make
sense for the pages a quality check flags, mainly drawings and failed scans. It was not run, and it
needs Dr. Namian's approval (estimates are at the end).

## What was compared

- **Pages.** `prototype/bakeoff/select_pages.py` picks the pages from the corpus audit, with the same
  result every run: 20 with more than 30% rotated text, 20 table pages with notes (spanned or two-row
  headers), 20 places where a table may run onto the next page, 15 scans with no text layer, 10
  landscape pages, 10 vector drawings, and 3 near-duplicate pairs (6 pages). Within each kind, pages
  are taken round-robin across documents, so the 2024 Standard Specifications cannot fill a kind by
  itself. The 16 gold pages of the 15 DAR-651 questions are added on top. Total: 117 pages from 38
  of the 60 documents (`prototype/bakeoff/pages.json`).
- **Candidates**, each run in its own environment on the same single-page PDFs:
  - **pymupdf4llm 1.28.2 + RapidOCR**: the current reader, called through `rag.loader` exactly as
    `prototype.ingest --ocr` calls it.
  - **Docling 2.147.0**: table structure on, RapidOCR set to `lang=["en"]` with `detect_orientation`
    on, 4 threads, CPU. The DAR-651 comparison ran with Docling's default OCR language, which is
    Simplified Chinese.
  - **MinerU 4.1.7** at `effort="medium"`: its local layout, OCR and table models, no VLM. It ran in
    process, so MinerU's local server, its CLI telemetry and its `--remote` mineru.net service were
    never used. It was forced onto the CPU: on this machine it picks DirectML and the RTX 5070 by itself.
  - **MinerU 4.1.7** at `effort="high"`: adds its 1.2B VLM through llama.cpp on the CPU. This was a
    timing sample only (see below).
  - **The text layer** (`page.get_text()`): the reference. On every page that has a text layer, it is
    the ground truth for which numbers and units are printed there.
- **Measures** (`prototype/bakeoff/measure.py`, scored by `report.py`):
  - **Cells right.** 30 hand-checked cells (`prototype/bakeoff/cells.json`). A cell counts as right
    when one output row holds both the value and its row label. A row under a row-spanned label also
    counts, but a value shifted into the next labelled row does not. Header cells must appear word for
    word. Cells on text pages were checked against the PDF's own text and row order. Scan cells come
    from the DAR-651 answers, which were checked against the page images.
  - **Numbers recall / precision.** The multiset of numbers each tool wrote, compared with the
    multiset in the text layer.
  - **Units kept.** The same comparison for ft, in, mph, %, ° and similar units.
  - **Tables found** on the pages where the audit's `find_tables` saw a table.
  - **Caption next to table.** A caption line ("Figure 4", "Table 6H-1") within 3 lines of a table.
  - **Header fragmentation.** The share of one- and two-letter words in table header rows.
  - **No-text pages read.** At least 100 characters from a page with no text layer.
  - **Speed.** Wall seconds and CPU seconds per page.
- **The machine was shared.** The bake-off ran alongside other index builds, with the CPU at 100%. Wall
  times are inflated, unevenly. CPU seconds (the process's CPU time over all its threads) are the fair
  comparison. "Corpus hours" is the mean wall time per page × 5,924 pages, so it is an upper bound.
- **Not measured here: the effect on the locked test set.** The locked set and its scorer (DAR-653)
  are not merged yet, and this ticket changes no pipeline code. If a tool is ever adopted for some
  pages, that measurement belongs in the coordinator's final locked-set run.

## Results

<!-- report:start -->
Pages: 117 (prototype/bakeoff/pages.json). Cells: 30 hand-checked (prototype/bakeoff/cells.json).

| Candidate | Pages read | Cells right | "Offset (ft)" verbatim | Numbers vs text layer (recall / precision) | Units kept | Table found on table pages | Caption next to table | Header fragmentation | No-text pages read | s/page (mean / median) | CPU s/page | Corpus hours | Install MB + models MB | Licence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| textlayer (pymupdf 1.28.2) | 117/117 | 13/30 | 2/2 | 1.00 / 1.00 | 1.00 | 0/67 | 0/0 | – | 0/26 | 0.02 / 0.01 | 0.01 | 0.00 | 55.60 + 0 | AGPL-3.0 (PyMuPDF) |
| pymupdf4llm (pymupdf4llm 1.28.2, pymupdf-layout 1.28.2, rapidocr 3.10.0, onnxruntime 1.30.0) | 117/117 | 24/30 | 0/2 | 0.95 / 0.93 | 0.90 | 49/67 | 23/28 | 0.13 | 21/26 | 4.03 / 1.44 | 8.52 | 6.60 | 412.40 + 0 | AGPL-3.0 (PyMuPDF, pymupdf4llm); RapidOCR Apache-2.0 |
| docling (docling 2.147.0, rapidocr 3.10.0, onnxruntime 1.31.1) | 117/117 | 23/30 | 0/2 | 0.87 / 0.97 | 0.62 | 47/67 | 23/27 | 0.08 | 22/26 | 16.95 / 15.34 | 19.47 | 27.90 | 1139.70 + 1060.00 | MIT (code); models Apache-2.0 / CDLA |
| mineru-medium (mineru 4.1.7) | 117/117 | 22/30 | 0/2 | 0.79 / 0.92 | 0.53 | 50/67 | 21/27 | 0.07 | 21/26 | 6.94 / 4.96 | 9.63 | 11.40 | 584.60 + 858.00 | MinerU Open Source License (Apache-2.0 + attribution, 100M MAU / USD 20M revenue cap) |
| mineru-high (mineru 4.1.7) | 14/14 | 1/1 | 0/0 | 0.75 / 0.77 | 0.69 | 10/12 | 3/5 | 0.01 | 0/0 | 132.32 / 4.51 | 434.84 | 217.70 | 584.60 + 2099.00 | MinerU Open Source License (Apache-2.0 + attribution, 100M MAU / USD 20M revenue cap) |

Number recall against the text layer and seconds per page, by page kind:

| Kind | Pages | textlayer | pymupdf4llm | docling | mineru-medium | mineru-high |
|---|---|---|---|---|---|---|
| drawing | 10 | 1.00 · 0.03 s | 1.00 · 5.84 s | 0.37 · 17.40 s | 0.39 · 6.44 s | – |
| gold | 16 | 1.00 · 0.01 s | 1.00 · 7.76 s | 0.96 · 22.64 s | 0.81 · 7.80 s | – |
| landscape | 10 | 1.00 · 0.01 s | 0.95 · 2.37 s | 0.71 · 13.47 s | 0.66 · 4.72 s | – |
| multi_page | 20 | 1.00 · 0.02 s | 0.98 · 2.00 s | 0.96 · 19.72 s | 0.94 · 6.09 s | 0.87 · 195.66 s |
| near_duplicate | 6 | 1.00 · 0.00 s | 1.00 · 3.71 s | 0.91 · 14.90 s | 0.91 · 4.42 s | – |
| rotated | 20 | 1.00 · 0.03 s | 0.85 · 2.48 s | 0.64 · 15.98 s | 0.48 · 6.97 s | 0.42 · 6.07 s |
| scan | 15 | – · 0.01 s | – · 8.03 s | – · 10.93 s | – · 6.53 s | – |
| spanned_header | 20 | 1.00 · 0.03 s | 0.88 · 1.67 s | 0.81 · 17.24 s | 0.70 · 9.52 s | 0.91 · 245.82 s |

Hand-checked cells (✓ read right, ✗ not):

| Page | Row | Value | textlayer | pymupdf4llm | docling | mineru-medium | mineru-high |
|---|---|---|---|---|---|---|---|
| wztc/TMP Design Manual (Combined, No Links).pdf#37 | (header) | Offset (ft) | ✓ | ✗ | ✗ | ✗ | – |
| wztc/TMP Design Manual (Combined, No Links).pdf#37 | (header) | Maximum Deflection (in) | ✓ | ✗ | ✗ | ✓ | – |
| wztc/TMP Design Manual (Combined, No Links).pdf#37 | 14 | 27.42 | ✗ | ✓ | ✓ | ✓ | – |
| wztc/TMP Design Manual (Combined, No Links).pdf#37 | 44 | 44.53 | ✗ | ✓ | ✓ | ✓ | – |
| wztc/TMP Design Manual (Combined, No Links).pdf#38 | (header) | Offset (ft) | ✓ | ✗ | ✗ | ✗ | – |
| wztc/TMP Design Manual (Combined, No Links).pdf#38 | 20 | 25.37 | ✗ | ✓ | ✓ | ✓ | – |
| wztc/TMP Design Manual (Combined, No Links).pdf#35 | Maximum Deflection | 12 ft. 10 in. | ✗ | ✓ | ✓ | ✓ | – |
| tmsd/09. At Grade Intersections.pdf#21 | SU-40 | 6.0 | ✗ | ✓ | ✓ | ✗ | – |
| tmsd/09. At Grade Intersections.pdf#21 | WB-62 | 100 | ✗ | ✓ | ✓ | ✗ | – |
| tmsd/09. At Grade Intersections.pdf#21 | WB-109D | 9.2 | ✗ | ✓ | ✓ | ✗ | – |
| tmsd/TODS Manual - September 2024.pdf#24 | Onslow | 067 | ✓ | ✓ | ✓ | ✓ | – |
| tmsd/TODS Manual - September 2024.pdf#24 | Mecklenburg | 060 | ✓ | ✓ | ✓ | ✓ | – |
| wztc/part6.pdf#39 | Large Arrow | 60 x 30 | ✗ | ✓ | ✓ | ✓ | – |
| wztc/part6.pdf#39 | Chevron Alignment | 18 x 24 | ✗ | ✓ | ✓ | ✓ | – |
| tmsd/04100.pdf#64 | (header) | (Number of Travel Lanes and Median Type) | ✓ | ✗ | ✗ | ✓ | – |
| tmsd/04100.pdf#64 | (header) | Recommendations for installing marked crosswalks | ✓ | ✓ | ✓ | ✓ | – |
| wztc/2024 Standard Specifications for Roads and Structures.pdf#444 | (header) | AGGREGATE GRADATION - COARSE AGGREGATE | ✓ | ✗ | ✗ | ✗ | – |
| wztc/2024 Standard Specifications for Roads and Structures.pdf#444 | (header) | Percentage of Total by Weight Passing | ✓ | ✗ | ✗ | ✗ | – |
| wztc/Division 11 Combined.pdf#4 | (header) | GENERAL NOTES FOR PILOT CAR OPERATIONS | ✓ | ✓ | ✓ | ✓ | ✓ |
| wztc/fhwahop14008.pdf#11 | (header) | Real-time Traveler Information | ✓ | ✓ | ✓ | ✗ | – |
| tmsd/C34 - Manual 2012.pdf#51 | E | Enter P.V.A. | ✓ | ✓ | ✓ | ✓ | – |
| tmsd/C34 - Manual 2012.pdf#50 | E | Enter P.P. | ✓ | ✓ | ✓ | ✓ | – |
| wztc/Chapter_2.pdf#40 | (header) | 20,000 | ✗ | ✓ | ✓ | ✓ | – |
| wztc/Chapter_5.pdf#4 | (header) | W8-11 | ✗ | ✓ | ✗ | ✓ | – |
| wztc/Chapter_5.pdf#4 | (header) | 2 inches | ✗ | ✓ | ✓ | ✓ | – |
| utilities/20220713 NCDOT UAM Ver 2-0.pdf#300 | (header) | removed by hand to a depth of 2 | ✗ | ✓ | ✓ | ✓ | – |
| utilities/010604.pdf#230 | C | 2,600 | ✗ | ✓ | ✓ | ✓ | – |
| utilities/010604.pdf#230 | B | 1,600 | ✗ | ✓ | ✓ | ✓ | – |
| utilities/010604.pdf#228 | (header) | flashing or revolving yellow light | ✗ | ✓ | ✓ | ✓ | – |
| utilities/20220713 NCDOT UAM Ver 2-0.pdf#244 | (header) | January 25, 1999 | ✗ | ✓ | ✓ | ✓ | – |

On the 14 pages mineru-high read (a timing sample: --sample picks pages spread over the list, and a stopped run keeps the first ones), all candidates:

| Candidate | Cells right | Numbers recall / precision | Units kept | s/page | CPU s/page |
|---|---|---|---|---|---|
| textlayer | 1/1 | 1.00 / 1.00 | 1.00 | 0.04 | 0.01 |
| pymupdf4llm | 1/1 | 0.92 / 0.92 | 0.99 | 2.78 | 5.93 |
| docling | 1/1 | 0.85 / 0.94 | 0.69 | 15.58 | 17.02 |
| mineru-medium | 1/1 | 0.74 / 0.77 | 0.69 | 5.41 | 6.68 |
| mineru-high | 1/1 | 0.75 / 0.77 | 0.69 | 132.32 | 434.84 |

Load and warm-up (first page, models loaded): textlayer 1.4 s + 0.0 s; pymupdf4llm 33.1 s + 26.2 s; docling 37.1 s + 29.6 s; mineru-medium 3.4 s + 57.0 s; mineru-high 2.0 s + 59.8 s.
<!-- report:end -->

## What the numbers say

- **Cells: a three-way tie.** pymupdf4llm got 24/30, Docling 23/30 and MinerU 22/30. The text layer
  alone got 13/30: it has the words but no rows. Each tool has its own failures:
  - All six cells pymupdf4llm misses are rotated or spanned headers (TMP p.37 and p.38, 04100 p.64,
    Standard Specifications p.444). The rows themselves come out right.
  - Docling misses the same six headers and also misread the "W8-11" line on the Chapter 5 scan.
  - MinerU reads two of those headers ("Maximum Deflection (in)" and the rotated 04100 header) but
    merged the At Grade Intersections turn-radius table (p.21) into one cell, with the numbers run
    together ("3535100105..."). That is a dangerous failure, because the digits are still on the
    page but no longer mean anything. It also dropped the fhwahop14008 p.11 heading.
- **None of the three reads a rotated header correctly.** "Offset (ft)" on TMP p.37 and p.38 comes out
  as fragments from all three tools: pymupdf4llm writes glyph pieces such as "ffs" into the row-label
  column, Docling writes "Offset 38" into a header cell, and MinerU leaves it out. The text layer has
  it word for word (2/2). The same
  happens to the sideways Table 1005-1 in the 2024 Standard Specifications (p.444): no tool keeps its
  caption or its spanned header. This is the geometry problem DAR-655 / U9 is fixing. Switching tools
  would not fix it.
- **Docling and MinerU drop text that pymupdf4llm keeps.** Number recall is 0.95 for pymupdf4llm, 0.87
  for Docling and 0.79 for MinerU. Page by page (number recall more than 0.05 apart), Docling is
  worse than pymupdf4llm on 42 pages and better on 3. MinerU is worse on 51 and better on 2. The losses are on drawings, where both treat the
  sheet as a picture and skip its vector text (number recall 0.37 and 0.39, against 1.00 for
  pymupdf4llm), on rotated pages (0.64 and 0.48, against 0.85) and on landscape pages.
- **The unit gap is lost text, not lost symbols.** On pages where a tool kept at least 90% of the
  numbers, it also kept 98–100% of the units. The lower "Units kept" figures for Docling and MinerU
  come from the drawings and rotated pages they skipped.
- **Scans are a tie.** pymupdf4llm read 21/26 no-text pages, Docling 22/26 and MinerU 21/26, and all
  three got the 8 scan cells except Docling's W8-11.
- **Where the other tools win, the fix is cheap.** The big wins are on two pages where pymupdf4llm
  returned nothing or nearly nothing:
  - the UAM soil-map page (p.286, which has 2,095 characters in its text layer; both win);
  - the Chapter 2 flagger drawing (p.39; MinerU wins).

  Plain `page.get_text()` already has those numbers, so no second tool is needed. Docling's other two
  wins are small (CFR part 924 p.6, 0.66 to 0.80, and part 655 p.7, 0.93 to 0.99).
- **Structure.** MinerU writes real HTML tables with `rowspan` and `colspan`. That is the best structure
  of the three, when its rows are right. The splitter and BM25 expect pipe tables, so adopting MinerU
  would also need an HTML-to-rows step.
- **Speed and size.**

  | Tool | Median CPU s/page | Mean CPU s/page | Install | Models |
  |---|---|---|---|---|
  | pymupdf4llm | 2.5 | 8.5 (OCR pages pull the mean up) | about 0.4 GB | none |
  | MinerU medium | 6.2 | 9.6 | about 0.6 GB | 0.9 GB |
  | Docling | 19.3 | 19.5 | 1.1 GB (with PyTorch) | 1.1 GB |

  Docling would add PyTorch to the build.
- **MinerU's VLM tier is not viable on a CPU.** The 30-page sample was stopped after 14 pages and 31
  minutes. The median page took 4.5 s, but two pages ran away: C34 p.52 took 1,219 s (about 4,000 CPU
  seconds) and the CFR part 924 p.6 took 580 s. On those 14 pages its number recall (0.75) was no better
  than MinerU medium's (0.74). The tier exists for GPUs, and this plan is CPU-only.

## Routing

| Pages | Tool | Why |
|---|---|---|
| All pages | pymupdf4llm + RapidOCR (unchanged) | Best or tied on every page kind in this sample |
| Rotated or spanned table headers | pymupdf4llm, with header text rebuilt from the text layer's rotated lines (DAR-655 / U9) | The text layer has "Offset (ft)" word for word; all three tools garble it |
| Pages where pymupdf4llm returns little or no text, or keeps under ~80% of the text layer's numbers | Add the raw text layer to the page (free) | Fixes UAM p.286 and Chapter 2 p.39, the only two pages where another tool won |
| Drawings, and scans whose OCR confidence stays low (DAR-658 / U16 flags) | Candidates for a paid vision model, **only with Dr. Namian's approval** | No local tool reads drawings better than the text layer, and OCR on old scans tops out |
| Docling or MinerU | Not routed to | They win no page class, lose numbers on 42 and 51 pages, and take more CPU per page (median 2.5× for MinerU, 8× for Docling) |

A cheap cross-check is the "Numbers vs text layer" comparison this bake-off uses. It works as a
build-time quality check (DAR-655 / U11), because the text layer is free ground truth on the roughly
5,750 pages that have one.

## Paid options (estimates only, not run)

These are list prices as of 2026-11-04 (`.handoff/redo-nov4/A-extraction.md`, section 6). Nothing was
sent to any service. **Any paid API or new vendor needs Dr. Namian's approval**, and only public NCDOT
documents could be sent. "Flagged pool" is the pages a quality check would most likely send: rotated
(142) ∪ scans (175) ∪ table pages (965) = 1,178 of the 5,924 pages (corpus audit). Most of those
1,178 are table pages that read fine today, so the real routed set would be smaller.

| Option | Price | Per page | Flagged pool (1,178 pages) | Whole corpus (5,924) | Evidence |
|---|---|---|---|---|---|
| Gemini 3 Flash (minimal thinking), page image + text-layer hint | USD 0.50 in / 3.00 out per 1M tokens; batch half | about USD 0.0066 (0.0033 batch), assuming about 1,120 image tokens in and 2,000 tokens out | about USD 7.8 (3.9 batch) | about USD 39 (19.5) | Vendor benchmarks (ParseBench tables 89.9, OmniDocBench TEDS 89.3); weak on large drawings (LED-Bench) |
| Mistral OCR 4 | USD 4 per 1,000 pages; USD 2 batch | USD 0.004 (0.002) | about USD 4.7 (2.4) | about USD 24 (12) | No independent table score for OCR 4; older Mistral OCR was weak on tables |
| PaddleOCR-VL-1.6 (open weights, Apache-2.0) | Free locally; rented GPU about USD 0.0002/page (one blog, MinerU-class model) | CPU about 33 s/page (one blog) | about 11 CPU-hours, or about USD 0.3 on a rented GPU (a new vendor) | about 54 CPU-hours | OmniDocBench leader (96.3, vendor-adjacent); no rotated-table score |

## How to rerun

```bash
# pages (needs the audit and the PDFs; the committed pages.json is the output)
.venv\Scripts\python -m prototype.bakeoff.select_pages --audit R:\_code_\RAG-Chatbot\.handoff\redo-nov4\corpus-audit.json --documents R:\_code_\RAG-Chatbot\hosted\documents
# text layer first: it splits the pages into <out>/pages/NNN.pdf
.venv\Scripts\python -m prototype.bakeoff.run --candidate textlayer   --out <out> --documents R:\_code_\RAG-Chatbot\hosted\documents
.venv\Scripts\python -m prototype.bakeoff.run --candidate pymupdf4llm --out <out>
# Docling and MinerU in scratch venvs (never .venv): uv venv --python 3.12 <venv>; uv pip install docling rapidocr onnxruntime / mineru
<docling-venv>\Scripts\python -m prototype.bakeoff.run --candidate docling --out <out>
<mineru-venv>\Scripts\python  -m prototype.bakeoff.run --candidate mineru --effort medium --out <out>
<mineru-venv>\Scripts\python  -m prototype.bakeoff.run --candidate mineru --effort high --sample 30 --out <out>
# score, and rewrite the tables between the report markers above
.venv\Scripts\python -m prototype.bakeoff.report --out <out>
```

Before parsing, MinerU downloads 0.86 GB of ONNX models, plus 1.24 GB of GGUF for `effort=high`, into
`~/.mineru/models`. That is well under the 5 GB limit set for this test. Docling downloads 1.1 GB into
the Hugging Face cache.
