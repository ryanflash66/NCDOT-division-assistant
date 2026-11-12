# Held-out test set: authoring notes for `utilities`

File: `evaluation/heldout/utilities.json`, 105 items (target 96, minimum 90; the extra items fill standing cases
and cover two documents that had no item). 97 are in the `locked` split and 8 in `tuning`.
`python -m evaluation.heldout.run validate` reports "270 items in 3 file(s): ok" (all three divisions' files).

The items were written from the 19 PDFs in `hosted/documents/utilities/` only, following
`.handoff/dar-661/AUTHORING-BRIEF.md`. None of the forbidden files (locked set, results, `hosted/index/`, the other
authors' held-out files) were opened, and no retriever, answerer or model was run on the questions. The helper
scripts are in `.handoff/dar-661/utilities/` and are not committed.

## How candidates were chosen

1. `dump.py` wrote the text layer of every page of every document to `text/<file>.txt`, with the page's
   exclusion flag (from `.handoff/dar-661/exclude-pages.json`), its split letter (`split_of` on
   `source|page`), its PDF label and its rotation. `overview.txt` lists one line per page with the corpus-audit
   flags (scans, rotation, tables, "continued", reserved, blank).
2. Pages were read in full for the short documents (Roadway Design Manual ch. 9, Utility Plans, the cost
   reimbursement memo, the companion guide on utility coordination and certification, the EDC-8 fact sheet, the
   2018 FHWA slides, the two FHWA case studies, the plan requirement sheet, the Encroachment Submissions User Guide
   pages used) and section by section for the UAM, the 1993 Highway/Utility Guide (`010604.pdf`), the Program
   Guide (`if03014.pdf`), the Rural Interstate Corridor study (`fhwahop09021.pdf`) and the two CFR parts.
3. Pages for each edge case were found by script and then read:
   - `listbreak.py`: pages that end in list items while the next page starts with list items (list_page_break).
   - `dupes.py` and `shared.py`: runs of 8 or more identical words shared with a page of another division's PDF
     (duplicate_section).
   - `ctx.py` / `grep.py`: regex search with context over the text layer and the OCR cache (symbols, reserved
     sections, refusal topics, competing answers).
   - `diffcfr.py`: sentence-level comparison of 23 CFR 645 as reprinted in the 2003 Program Guide with the 2024
     CFR (superseded).
   - `cand.py`: split, exclusion, label and folio guesses for candidate pages.
4. Tables, scans, rotated pages, figures and slides were rendered with PyMuPDF (`render.py`, PNG in `png/`) and
   read from the image. The scanned pages without a text layer (UAM appendix memos pp. 246-260 and 297-305,
   Highway/Utility Guide pp. 231-316) were run through rapidocr 3.x (`ocr.py`, text in `ocr/`).
5. For the priority cases the split of a candidate page was looked up before writing, and locked pages were
   preferred so that at least 4 of the 5 required pages fall in `locked`. Questions were never reworded to change
   a split, and refusals take the split their question text hashes to. Because of this page preference the set
   has fewer `tuning` items (8 of 105) than the 3-in-16 hash rate would give on random pages (about 20).
6. When a topic is generic, the other documents of the division were searched for a competing value; where two
   documents differ, the question names its document (for example the ASCE 38 edition, the plan requirement
   sheets, the 2003 reprint of 23 CFR 645).

Items live in `items_data.py`, `batch1b.py`, `batch2.py` and `batch3.py`; `build_items.py` numbers them, computes
`split` with `evaluation.locked.split_of` and writes the JSON. Printed page numbers were read from each page: the
header or footer folio ("3-11", "A-3", "B-16", "4-29"), the sideways folio of rotated pages ("33", "61", "96"), the
page number of an attached report ("10" for the soil report inside UAM Appendix F), "1" for "Page 1 of 2", or ""
when the page prints none. `fhwahop09021.pdf` has PDF page labels, so its item uses the label ("81") as the brief
asks; the page also prints "6-2" (see misfits).

## How items were verified

`verify.py` runs over every item and exits non-zero on any failure. The final run checks 105 items with no
failure.

- Answerable items: `value_matches(value, accept, page_text)` must hold on a gold page, and every `all_of` part
  must match on at least one gold page.
  - `page_text_match` (82 items): text layer of the gold page.
  - `ocr_text_match` (6 items, scanned UAM memos and the Indiana permit form): OCR text of the page. The script
    also reports when the value is in the text layer as well.
  - `page_image_read` (17 items): read off the rendered page, then checked against the text layer plus the OCR
    text of the page. Two table cells carry a bare number whose unit is only in the table heading (h047 "13.0",
    heading "Clearance (ft)"; h048 "42", heading "Depth of Cover (in inches)"); the script accepts the bare number
    for these and prints a note. Three values could not be text-checked at all because the page has no text layer
    and the OCR text does not show them in a usable order: h054 (Virginia row of Table 12-1), h056 (the 1 1/2-inch
    glyph on the Indiana permit form) and h084 (Missouri row of Table 12-1). They were read from the image only.
- Every gold page is checked against `exclude-pages.json`; `printed_pages` must have one entry per PDF page; no
  gold page holds more than 2 items. Fourteen pages hold 2 items (UAM pp. 85, 103, 107, 110, 124, 176, 187; RDM
  ch. 9 p. 7; cost memo p. 2; `010604.pdf` pp. 103, 105, 278; companion guide p. 2; user guide p. 6); the other 70
  gold pages hold 1. There are 84 distinct gold pages.
- Tags are checked against `evaluation.heldout.EDGE_CASES`.
- `correct` items: the wrong value is in the question and is not matched by the value or any accept.
- Refusals: each item carries regexes for the thing asked; `verify.py` searches the text layer of all 19
  documents and every OCR cache file. A hit fails unless the regex is marked as reviewed, in which case the note
  explains the hit (for example "Hydrogen Film" as a drawing label, or the "[Reserved]" marker itself).

## Counts

Behaviour: 83 answer (78 locked), 12 refuse (10 locked), 5 clarify (4 locked), 5 correct (5 locked).
Askers: 51 `wztc`, 48 `tmsd`, 6 `utilities` (about 6%).

| type | total | locked | tuning |
|---|---|---|---|
| text | 64 | 59 | 5 |
| unanswerable | 12 | 10 | 2 |
| scan | 7 | 7 | 0 |
| table | 7 | 7 | 0 |
| figure | 5 | 5 | 0 |
| rotated | 4 | 4 | 0 |
| cross_ref | 3 | 3 | 0 |
| multipage_table | 3 | 2 | 1 |

| document | items | locked |
|---|---|---|
| 20220713 NCDOT UAM Ver 2-0.pdf | 39 | 35 |
| 010604.pdf (FHWA Highway/Utility Guide, 1993) | 16 | 15 |
| 09. Right of Way.pdf | 7 | 7 |
| CFR-2024-title23-vol1-part645.pdf | 5 | 5 |
| if03014.pdf (Program Guide) | 4 | 4 |
| NCDOT Utility Cost Reimbursement Guidance_8-20-2026.pdf | 3 | 3 |
| 09utilcoordcert.pdf | 3 | 3 |
| hif22040.pdf | 3 | 3 |
| hif22002.pdf | 2 | 2 |
| CFR-2024-title23-vol1-part710.pdf | 2 | 2 |
| utility_row.pdf | 2 | 2 |
| DOT Encroachment Submissions User Manual - July 2023.pdf | 2 | 2 |
| EDC-8_Factsheet_SUE.pdf | 1 | 1 |
| fhwahop09021.pdf | 1 | 1 |
| Utility-Encroachment-Plan-Requirements.pdf | 1 | 1 |
| 18. Utility Plans.pdf | 1 | 1 |
| UtilitiesCoordination-Encroachments-presentation-notes.pdf | 1 | 0 |
| (refusals, no source) | 12 | 10 |

The pole memo (`Encroachment_Requirements_Involving_Excessive_Height_Direct_Bury_Poles`) and the 16-1 two-party
agreement form have no item: the memo's rule page (p. 1) is excluded and p. 2 is a cc list, and both pages of the
16-1 form are excluded. The presentation notes are mostly navigation directions for web pages, so they have one
item.

Per tag ("P" marks the priority cases; gold pages counts distinct first gold pages; refusals have none):

| tag | priority | total | locked | gold pages | locked gold pages |
|---|---|---|---|---|---|
| degraded_scan | P | 6 | 6 | 5 | 5 |
| range_threshold | P | 10 | 9 | 9 | 8 |
| conditional | P | 7 | 7 | 7 | 7 |
| superseded | P | 2 | 2 | 2 | 2 |
| multi_column | P | 11 | 11 | 10 | 10 |
| symbols | P | 6 | 6 | 6 | 6 |
| not_in_documents | P | 5 | 4 | - | - |
| false_premise | P | 5 | 5 | 5 | 5 |
| duplicate_section | P | 5 | 5 | 5 | 5 |
| toc_decoy | P | 5 | 5 | 5 | 5 |
| list_page_break | P | 5 | 5 | 5 | 5 |
| missing_variable | P | 5 | 4 | 5 | 4 |
| revision_marks | P | 6 | 5 | 2 | 2 |
| printed_vs_pdf |  | 15 | 15 | 14 | 14 |
| chapter_page |  | 31 | 27 | 25 | 22 |
| appendix_page |  | 3 | 3 | 2 | 2 |
| near_identical |  | 5 | 4 | 5 | 4 |
| not_first_row_col |  | 10 | 9 | 9 | 8 |
| multipage_table |  | 3 | 2 | 3 | 2 |
| merged_header |  | 3 | 2 | 3 | 2 |
| rotated |  | 4 | 4 | 4 | 4 |
| scan |  | 21 | 20 | 18 | 17 |
| footnote |  | 4 | 3 | 4 | 3 |
| units |  | 15 | 15 | 13 | 13 |
| cross_reference |  | 3 | 3 | 3 | 3 |
| two_pages |  | 5 | 5 | 5 | 5 |
| conflicting_documents |  | 3 | 3 | 3 | 3 |
| figure |  | 6 | 6 | 5 | 5 |
| form |  | 3 | 3 | 3 | 3 |
| out_of_scope |  | 3 | 3 | - | - |
| precision |  | 10 | 9 | 9 | 8 |
| rephrased |  | 3 | 2 | 3 | 2 |
| table_id |  | 14 | 13 | 13 | 12 |

Notes on the priority cases:

- `revision_marks` covers 5 different reserved places: 23 CFR 710.407 (part 710 p. 12), 645.209(c)(2)(iv) in the
  2024 CFR (part 645 p. 14), 646.202 (part 645 file p. 19), 23 CFR 750 Subpart C (part 710 file p. 23) and the
  2003 reprint of 645.209(c)(2)(iv) (`if03014.pdf` p. 93). Four are refusals about the reserved item; two are
  `answer` items about the live text right after "(iv) [Reserved]" (part 645 p. 14 and `if03014.pdf` p. 93).
  The division has no strikethrough, revision bars or draft watermarks; the UAM's "This page intentionally left
  blank" pages were not used because a question about an empty page has no practical wording.
- `not_in_documents` (5) and `out_of_scope` (3) are refusals; the regexes and the hits that were reviewed are in
  each note.
- `false_premise`: 5 `correct` items (CFR 710 notice to vacate, companion guide certification, UDOT agreement
  terms, HB 1094 signing date, UAM cored slab bridges). No `refuse` false premises were added.
- `toc_decoy` items use the list-of-tables or contents wording; the gold page is always the content page.
- `duplicate_section` pages were confirmed against the other division's page: UAM p. 51 (Policy on Access manual and
  TSLG), UAM p. 140 and p. 147 (TSLG), UAM p. 187 (C34 manual glossary), part 645 p. 12 (TMP
  Design Manual p. 25).

## Cases that are absent or short, and the check

- `superseded`: 2 items (both locked) on 2 pages, short of 5. Only two older/newer pairs of the same rule exist
  in the division:
  - ASCE 38: the 2023 EDC-8 fact sheet cites ASCE 38-22; UAM p. 23 and `hif22002.pdf` p. 5 cite 38-02 (item h044;
    h103 asks the old edition from the named case study and is tagged `conflicting_documents`, not `superseded`).
  - Standard Utility Encroachment Plan Requirements: April 2021 sheet in UAM Appendix C (pdf pp. 201-202) and the
    July 2023 standalone sheet. Compared line by line: the only changed rule is the utility structure requirement
    (2021: NCDOT Approved Products List number; 2023: ANSI tier rating outside pavement or AASHTO HS-20 under
    pavement, plus vaults from the Qualified ITS and Signals list). Other changes are "should" to "shall" and
    "if requested by NCDOT". Item h085. Page 2 of the 2023 sheet is excluded.
  Checks that found no other pair: `diffcfr.py` (2003 reprint of 23 CFR 645 against the 2024 CFR: wording only,
  e.g. "highway agencies" to "transportation departments", OMB spelled out, typos; item (iv) is "[Reserved]" in
  both; no changed number or rule); the July 2016 sheet in UAM Appendix C (pp. 199-200) is a different guidance
  (agreement routes, project descriptions, signatures), not an older edition of the plan requirements; the 2026
  pole memo has its only rule page (p. 1) excluded and p. 2 is a cc list; the 2026 cost memo pages 3-4 are
  excluded and the rest does not restate an older value; RDM ch. 9 pages carry one revision date each
  (07/12/07, 02/08/02) with no older text alongside.
- Every other priority case has at least 5 items on at least 5 different pages with at least 4 locked.
- Every standing case has at least 3 items. `appendix_page` has 3 items on 2 gold pages (UAM glossary A-3 and the
  soil report inside UAM Appendix F); `rotated` has 4 (three sideways landscape pages of `010604.pdf` and the
  rotated UAM soil report legend; UAM pp. 194, 269 and 270 are rotated but excluded).

## Schema and scorer misfits

- `value_matches` compares a single number numerically against every number in the answer. Several gold values
  are small integers (h005 "1" uplight rating, h010 "2" safety factor, h012 "60" psig without the unit in the
  value); any other "1" or "2" in an answer, citation markers included, would satisfy them.
- A phrase value is a substring match, so short phrase values pass on unrelated text: h071 "three" (number of
  ways into the Permits site) and h087 "prohibited". h071 relies on `all_of` for the real check; h087 has no
  `all_of`.
- `correct` items expect a number or fact; h087's wrong premise is a permission ("lets utilities hang conduit on
  cored slab bridges") and the true value is the word "prohibited".
- Reserved-section refusals: the documents do contain the marker "[Reserved]", so the right reply ("it is
  reserved") is a statement backed by a page. If the scorer treats any cited page on a `refuse` item as a failure,
  these 4 items will penalise a correct answer.
- `printed_pages` for `fhwahop09021.pdf` follows the brief's label rule ("81"), but the page itself prints "6-2".
  For UAM p. 286 the only number printed is the soil report's own page "10"; the UAM folio is not on the page.
- `page_image_read` values in table cells whose unit lives only in the column heading cannot be matched by
  `value_matches` against the page text with the unit; the verification falls back to the bare number (h047, h048).
- h077 asks the reader to decode a label ("2\" MP DI MAIN 1948") with the legend of Figure 4-11; that label is
  built from the legend and is not printed on the page (the figure prints its own example "4\"LP CI MAIN 1932").
- h080: the page prints the formula result as "Accrued Appreciation" (a typo for depreciation); the question
  avoids the word.
- h083 (clarify) is also tagged `symbols`: the urban branch value is printed as the glyph "½"; the accept list
  includes "1/2 mile", "0.5 mile" and "½ mile".

## Helper scripts (`.handoff/dar-661/utilities/`)

`dump.py`, `compact.py`, `overview.txt`, `ov2.py` (page text and audit overview); `grep.py`, `ctx.py`, `show.py`,
`cand.py` (search and page inspection); `dupes.py`, `shared.py` (cross-division duplicates); `diffcfr.py`
(2003 vs 2024 CFR 645); `listbreak.py` (lists across page breaks); `render.py`, `ocr.py` (page images and OCR
cache); `items_data.py`, `batch1b.py`, `batch2.py`, `batch3.py` (the items); `build_items.py` (writes the JSON);
`verify.py` (checks); `counts.py` (the tables above).
