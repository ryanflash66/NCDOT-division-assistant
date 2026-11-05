# Locked test set: Transportation Mobility and Safety (`tmsd`)

`evaluation/locked/tmsd.json` holds 100 items: 85 answerable and 15 that must be refused. The schema and split rule are the DAR-652 shared contract: `split` comes from `sha1(f"{source}|{pdf_pages[0]}")`, or from the question for unanswerable items, and was computed in code, never set by hand. The result is 84 locked and 16 tuning items. Askers alternate between `wztc` (51) and `utilities` (49), so every item is a cross-division question.

## How the items were written

- Candidate pages came from the corpus audit (`.handoff/redo-nov4/corpus-audit.json`): table pages (`nt`, `tabtop`/`tabbot`/`cont`), landscape and rotated pages, pages with fewer than 10 characters, and the page labels. They were then read in the PDFs in `hosted/documents/tmsd/`.
- None of the questions come from the dev sets (`eval/*.json`, `evaluation/testset.json`). The DAR-651 guardrail question (`tmsd-guardrail-l1`) inspired the guardrail drawing items, but none of them repeats it.
- Each item asks for a single fact. `accept` holds only other spellings of that fact, never the other half of a two-part answer, because the scorer passes an answer that matches any one entry. Neighbouring cells and values that look similar are listed in `note` as decoys.
- `verified_by`:
  - `page_text_match` (72): `expected.value` was found on a gold page's pymupdf text layer after normalisation (case, thousands commas, quote and dash variants, whitespace).
  - `ocr_match` (7): the same check against RapidOCR text at 200 dpi, for pages with no text layer: the 01102.pdf documentation page (p.3) and guardrail drawing pages 13, 15, 23 and 28.
  - `visual` (6): the value is only in an image that OCR does not read cleanly, so it was read from the rendered page:
    - Guardrail Detail 3-2A, p.10 (2 items): the table inside the drawing
    - Guardrail Detail 3-2B, p.12: OCR reads "CAT-1" as "CATI"
    - At Grade Figure 3 formula, p.35
    - Directional crossover drawing, p.39
    - Signal Timing Philosophy Figure 1, p.17: a rotated flow chart
- A scratch validator checked:
  - required keys, the type enum, unique ids and questions
  - every `source` is a tmsd file in `hosted/divrag/divisions.py`
  - every `pdf_pages` is within the PDF's page count and `printed_pages` has the same length
  - the split rule, `refuse` ⇔ `expected: null` ⇔ `type: unanswerable`, and the asker is never `tmsd`
  - every text- or OCR-verified value is on a gold page

  It reports 0 errors. The DAR-653 scorer's `evaluation.locked.validate` (U1 branch) also passes: "100 items in 1 file(s): ok".
- `printed_pages`:
  - Taken from the page's header or footer, or from the PDF page label (STEP guide p.3 = "i").
  - The Roadway Design Manual chapters (`03. Guardrail…`, `09. At Grade…`) print only section or detail labels (for example "3-2A"), never page numbers. Their printed page is `""` and the label is recorded in `note`.
  - The Signal Timing Philosophy Manual restarts "Page N" in every section, so "Page 3" appears on PDF p.17 and on PDF p.38.

## Counts

| type | items | locked | tuning |
|---|---|---|---|
| table | 33 | 28 | 5 |
| text | 24 | 18 | 6 |
| unanswerable | 15 | 13 | 2 |
| figure | 9 | 7 | 2 |
| multipage_table | 4 | 4 | 0 |
| footnote | 3 | 3 | 0 |
| table_id | 3 | 2 | 1 |
| cross_ref | 2 | 2 | 0 |
| rotated | 2 | 2 | 0 |
| scan | 2 | 2 | 0 |
| units | 2 | 2 | 0 |
| duplicate_pages | 1 | 1 | 0 |

`type` is the main thing each item tests. `edge_cases` lists everything else it exercises (an item can have several):

| edge case | items | locked | tuning |
|---|---|---|---|
| non_first_row | 37 | 30 | 7 |
| printed_vs_pdf | 35 | 27 | 8 |
| non_first_column | 24 | 20 | 4 |
| table_id ("Table 2C-5", "TOD-7", "Detail 3-2A") | 17 | 11 | 6 |
| merged_header | 16 | 13 | 3 |
| landscape | 11 | 9 | 2 |
| numeric_precision | 11 | 10 | 1 |
| out_of_scope | 10 | 9 | 1 |
| scan (no text layer beyond the running header) | 10 | 8 | 2 |
| multipage_table | 9 | 8 | 1 |
| drawing | 8 | 6 | 2 |
| figure_callout | 7 | 7 | 0 |
| footnote | 7 | 7 | 0 |
| rotated | 7 | 7 | 0 |
| false_premise | 5 | 4 | 1 |
| phrasing_drift | 5 | 4 | 1 |
| chapter_page (FHWA "5-13" style) | 4 | 3 | 1 |
| conflicting_values | 3 | 2 | 1 |
| near_duplicate | 3 | 3 | 0 |
| units | 3 | 3 | 0 |
| cross_ref | 2 | 2 | 0 |
| roman_front_matter | 1 | 1 | 0 |
| toc_decoy | 1 | 1 | 0 |
| two_page_question | 1 | 1 | 0 |

Figure and drawing items: 9 `figure` items plus the rotated directional-crossover drawing make 10.
- Guardrail chapter (7): Details 3-2A (2), 3-2B, 3-2C and 3-2D, Figure 1 (special grading), and Table 1 on rotated p.28 (2 more items, typed `table`).
- At Grade Intersections: Figure 3 and the 9-4 directional crossover.
- Signal Timing Philosophy Manual: Figure 1.
- TODS manual: the application flow chart.

The tables requested in the plan are covered:
- Signal Timing Philosophy Manual tables: performance goals, data needs, cost-benefit Table 1 and the revision grid.
- TODS manual: the TOD-7 county code table, plus text items on the TOD forms and fees, and the application flow chart.

| document | items | locked | tuning |
|---|---|---|---|
| 03. Guardrail, Barriers and Attenuators.pdf | 16 | 14 | 2 |
| 09. At Grade Intersections.pdf | 8 | 8 | 0 |
| Signal System Timing Philosophy Manual.pdf | 8 | 6 | 2 |
| TODS Manual - September 2024.pdf | 7 | 5 | 2 |
| 04100.pdf | 4 | 4 | 0 |
| CFR-2024-title23-vol1-part655.pdf | 4 | 4 | 0 |
| Chapter2c.pdf | 4 | 3 | 1 |
| L18_TSLG_Guide.pdf | 4 | 4 | 0 |
| Policy on Access Manual.pdf | 4 | 3 | 1 |
| fhwa_hop_08_024.pdf | 4 | 3 | 1 |
| interim-design-safety-pilot-program.pdf | 4 | 2 | 2 |
| 01102.pdf | 3 | 3 | 0 |
| 04091.pdf | 3 | 3 | 0 |
| C34 - Manual 2012.pdf | 3 | 3 | 0 |
| Fatal Investigation Guidelines.pdf | 3 | 2 | 1 |
| STEP-guide-improving-ped-safety.pdf | 2 | 2 | 0 |
| part3.pdf | 2 | 1 | 1 |
| CFR-2024-title23-vol1-part924.pdf | 1 | 0 | 1 |
| bikeped_Ped_Policy.pdf | 1 | 1 | 0 |
| (unanswerable) | 15 | 13 | 2 |

## Unanswerable items (15)

- 10 out-of-scope questions:
  - other states (VDOT, SCDOT)
  - prices, statistics and dollar amounts that the documents don't hold
  - an 80 mph value beyond Detail 3-2A's 40–70 mph range
  - two questions whose answers live in other divisions' manuals (wztc TMP deflection, utilities bore-and-jack cover)
- 5 false-premise questions with the number or rule reversed. A correct reply refuses or corrects the premise and never echoes it.

## Gaps and limits of the tmsd corpus

- **Rumble strips are not covered.** `Revised Rumble Strip Guidelines.pdf` is in `hosted/documents/tmsd/` and the audit (9 image-only pages), but it is not a registered tmsd document in `divisions.py`. It is therefore not indexed, and no answer can cite it. The 10 drafted items (5 OCR text items on pp.1–3, 5 drawing items on pp.4–7) were left out.

  Should the memo be registered, the drafts to re-verify and add are:
  - p.1: strip moved from 3 ft to 6 in from the travel lane (OCR); March 2005 letting (OCR); contact Art McMillan (OCR)
  - p.2: Roadway Standard Drawing 720.01 for concrete shoulders (OCR)
  - p.3: State Highway Design Engineer approves other treatments (OCR)
  - p.4: milled depth 1/2 in on asphalt and 12 in typical spacing (drawing)
  - p.5: ends 25 ft before an intersection radius (drawing)
  - p.6: concrete stamped or rolled strip width 24 in (drawing)
  - p.7: concrete milling stops 8 1/2 in from transverse joints (drawing)

  The rumble false-premise item stays: a refusal is the grounded reply today.
- **Few true scans.** Apart from the rumble memo, the tmsd PDFs have almost no scanned text pages. The pages under 10 characters that were OCR-checked (01102 pp.47, 67, 89, 105; 04091 pp.20–112; 04100 pp.22, 60, 72) came back empty. The only other non-empty one is the 01102.pdf conversion table (p.4), which OCR garbles. So `scan` as a type has 2 items (01102 p.3). Another 8 items sit on guardrail drawing pages whose only text layer is the running header, and they carry `scan` as an edge case.
- Thin rows: `cross_ref` (2), `two_page_question` (1), `toc_decoy` (1) and `duplicate_pages` (1: the bikeped cost-participation table printed on both pp.4 and 11).
- The TODS mainline-panel border width (p.42) is not in the set: its fraction glyph does not extract ("�� flush outside border"), so it could not be verified from text.
