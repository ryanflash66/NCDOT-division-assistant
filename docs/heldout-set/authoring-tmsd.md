# Held-out set: authoring notes for tmsd (Transportation Mobility and Safety)

File: `evaluation/heldout/tmsd.json`, 106 items (98 locked, 8 tuning). Every item was written from the page, checked by
script, and the file passes `python -m evaluation.heldout.run validate`. The helper scripts are in
`.handoff/dar-661/tmsd/`.

## How the set was built

The items live as short Python dicts in `.handoff/dar-661/tmsd/items1.py` to `items4.py`. `build.py` loads them in
that order, gives them the ids `tmsd-h001` to `tmsd-h106`, computes the split with `evaluation.locked.split_of`, checks
each item, prints the counts and writes the JSON. A rebuild renumbers the ids, so an id is only stable for this
version of the file.

Candidate pages came from four places:

- the corpus audit (`.handoff/redo-nov4/corpus-audit.json`): scans, rotated pages, tables and continuation markers;
- my own surveys:
  - `scaninfo.py`: full-page images with their DPI;
  - `survey.py dup`: 8- and 12-word shingles shared with the wztc and utilities PDFs;
  - `survey.py marks`: Reserved, intentionally blank, expired, repealed, superseded, rewritten, draft;
  - `survey.py cols`: two-column pages;
  - `listbreak.py`: lists that run onto the next page;
  - a symbol scan for ≥, ≤, ± and similar glyphs;
- regex searches with `find.py`;
- reading the documents themselves.

The first tmsd author left drafts and notes. I treated them as leads only. I re-read the page for each of their items
and kept 14 of them (`items2.py`). Their remaining ideas I either re-verified and rewrote, or dropped.

Rules followed for every item:

- No gold page is in `.handoff/dar-661/exclude-pages.json`.
- No page carries more than 2 items, and most carry one.
- No question names its page number or copies a page sentence word for word.
- Wherever another tmsd document gives a competing value, the question names its document.

## Verification (build.py)

- **Text pages** (`page_text_match`, 92 items): the value and every `all_of` part must pass
  `normalize.value_matches` on the text layer of the gold pages. For matching only, build.py also:
  - turns U+2010/U+2011 hyphens and no-break spaces into plain characters;
  - adds a second copy of the page with line-end hyphens joined.

  This was needed for the Signal System Timing Philosophy Manual (SSTP) and the CFR pages.
- **Printed page:** must equal the PDF page label. When a page has no label, the printed number must be a whole token in
  the page's first 12 or last 3 text lines.
  - Four Roadway Design Manual (RDM) figure sheets are image-only, so their sheet ids were read off the rendered image
    and marked `printed_ok`. These are RDM ch. 3 p3 (3-1) and RDM ch. 9 p2 (F-1), p7 (F-3A-2) and p13 (F-4A).
- **Scans** (`page_image_read`, 13 items): I rendered each page to PNG with PyMuPDF and read the value off the image,
  including drawings, rotated pages and low-DPI scans. With `--ocr`, build.py also runs RapidOCR. The value is often
  not in the OCR text either (fractions, blurred tables), so for these items the image reading is the evidence.
- **OCR** (`ocr_text_match`, 1 item: Access policy p9, "10th day of July"): the value must be in the RapidOCR text and
  must not be in the text layer. OCR results are cached in `ocr_cache.json`.
- **Refusals** (13): every `absent` regex is searched across all 19 tmsd documents. Any hit must be explained by an
  `absent_ok` entry, and every explanation is in the item note. For a reserved or expired rule, the marker text must
  be on the named page (`reserved_on`).
- **`correct` items:** the wrong premise value must not match the gold value or any accept string.
- **`clarify` items:** each item has 2 branches in `all_of`, and the note names the missing variable.

## Notes a reader needs

- **Rumble strip PDF not used.** `hosted/documents/tmsd/Revised Rumble Strip Guidelines.pdf` is in the folder but not
  in `hosted/divrag/divisions.py`, so no item uses it, and the refusal absence checks do not search it.
- **RDM sheets print no page numbers.** The Roadway Design Manual chapters show only a section id ("3-2E") or, on figure
  and table sheets, a sheet id ("F-4A", "T-3"). `printed_pages` carries that id.
- **SSTP page numbers restart.** Each SSTP section starts again at "Page 1", and the folio sits a few lines under the
  header.
- **Traffic Services Legal Guide (L18) and the CFR files.** L18 has no page labels; its folio is "Page N of 706". The
  CFR files print the CFR page (385, 606 …).
- **Duplicate flowchart.** The TODS flow chart scan (PDF p28, item on the 60-day fee time frame) has a near-identical
  copy with a text layer on PDF p44, which is excluded. A retriever that reads p44 can find the value, so this
  degraded-scan item is weaker than the other four.
- **Turn-lane pair (near_identical).** The Access policy turn-lane table (PDF p88) and RDM ch. 9 Figure 4 (F-4A, PDF
  p13) are the same exhibit. Each question names its document.
- **SI conversion table (near_identical).** The table on 01102 p4 (blurred scan) also has a text layer in 04091 p4 and
  04100 p4. The question names the Pedestrian Facilities Users Guide.
- **Walking speeds (conflicting_documents).** The documents disagree:
  - 01102 p97 says a maximum of 3.5 ft/s;
  - the Signal Timing Manual p140 and the Signalized Intersections guide p47 say the MUTCD uses 4.0 ft/s.

  Each of the three questions names its document.
- **Duplicate wording that differs in one word.** Access p80 says "District Engineer", while the same sentence in the
  utilities form 16-1 says "Division Engineer". The question tests that difference.
- **Fewer items in some documents.** Several FHWA guides are long, but most of their pages are excluded or already
  covered, and part3.pdf (MUTCD Part 3) has no item. The set is above the 96 target (106) because the extra items were
  needed to fill the toc_decoy, revision_marks and cross_reference quotas on locked pages.

## Counts

Askers: wztc 50, utilities 50, tmsd 6 (wztc/utilities about 94%). Behaviours: answer 83, refuse 13, clarify 5, correct 5.

| type | total | locked | tuning |
|---|---|---|---|
| text | 59 | 56 | 3 |
| unanswerable | 13 | 8 | 5 |
| table | 8 | 8 | 0 |
| rotated | 6 | 6 | 0 |
| units | 6 | 6 | 0 |
| figure | 5 | 5 | 0 |
| multipage_table | 4 | 4 | 0 |
| cross_ref | 2 | 2 | 0 |
| footnote | 2 | 2 | 0 |
| scan | 1 | 1 | 0 |

| edge case | total | locked | tuning | distinct gold pages |
|---|---|---|---|---|
| degraded_scan | 5 | 5 | 0 | 5 |
| range_threshold | 8 | 8 | 0 | 8 |
| conditional | 5 | 5 | 0 | 5 |
| superseded | 2 | 2 | 0 | 2 |
| multi_column | 6 | 6 | 0 | 5 |
| symbols | 5 | 5 | 0 | 5 |
| not_in_documents | 6 | 4 | 2 | (refusals) |
| false_premise | 5 | 5 | 0 | 5 |
| duplicate_section | 5 | 5 | 0 | 5 |
| toc_decoy | 5 | 5 | 0 | 5 |
| list_page_break | 5 | 5 | 0 | 5 |
| missing_variable | 5 | 5 | 0 | 5 |
| revision_marks | 6 | 4 | 2 | (refusals) |
| printed_vs_pdf | 23 | 23 | 0 | 21 |
| chapter_page | 5 | 5 | 0 | 5 |
| appendix_page | 3 | 3 | 0 | 2 |
| near_identical | 3 | 3 | 0 | 3 |
| not_first_row_col | 13 | 13 | 0 | 11 |
| multipage_table | 4 | 4 | 0 | 4 |
| merged_header | 4 | 4 | 0 | 3 |
| rotated | 6 | 6 | 0 | 5 |
| scan | 9 | 9 | 0 | 8 |
| footnote | 3 | 3 | 0 | 3 |
| units | 16 | 16 | 0 | 16 |
| cross_reference | 3 | 3 | 0 | 3 |
| two_pages | 6 | 6 | 0 | 6 |
| conflicting_documents | 3 | 3 | 0 | 3 |
| figure | 8 | 8 | 0 | 8 |
| form | 5 | 5 | 0 | 5 |
| out_of_scope | 3 | 1 | 2 | (refusals) |
| precision | 7 | 7 | 0 | 6 |
| rephrased | 10 | 8 | 2 | 10 |
| table_id | 11 | 11 | 0 | 11 |

Items per document:

| document | items |
|---|---|
| TODS Manual | 16 |
| Policy on Street and Driveway Access | 12 |
| STEP guide | 9 |
| Signal System Timing Philosophy Manual | 8 |
| Traffic Services Legal Guide (L18) | 8 |
| RDM ch. 3 | 5 |
| RDM ch. 9 | 5 |
| Pedestrian Policy | 5 |
| Interim design safety pilot | 5 |
| CFR 655 | 4 |
| CFR 924 | 4 |
| C34 (DMV-349 manual) | 3 |
| Fatal Investigation Guidelines | 2 |
| 01102 | 2 |
| FHWA Signal Timing Manual | 2 |
| 04100 | 1 |
| 04091 | 1 |
| MUTCD Chapter 2C | 1 |

The remaining 13 items are refusals and have no gold document.

## Edge cases that are short or absent, and the checks that showed it

**superseded: 2 items (quota 5).** A real older and newer version of the same rule occurs only twice:

- **G.S. 136-18(10).** It is printed in its "(Effective until January 1, 2021)" and "(Effective January 1, 2021)"
  versions (L18 p371-372).
- **G.S. 20-4.01(48a), U-drive-it vehicles.** Both versions are on L18 p243: "(Effective until December 31, 2024)" and
  "(Effective December 31, 2024)".

Checks that found no other case:

- Searched L18 for every parenthesized "(Effective …)", "(Repealed …)" and "(Expires …)" marker; it hits only
  p243, 248, 371 and 372.
- p248 (§ 20-37.6, "Effective March 1, 2020") has no older version in the guide.
- `survey.py marks` for "superseded / rewritten / recodified" in all 19 documents. The hits are unrelated statute
  wording: L18 p235, 340, 348, 355, 363 and 364, and Signal Timing Manual p76.
- MUTCD editions:
  - Chapter2c.pdf and part3.pdf are both the 11th Edition (December 2023).
  - The SSTP lists the 2003 MUTCD only as a reference (p60) and states no rule from it.
  - The TODS note "Business logos can now be on TODS signs per 11th Edition MUTCD" (p38) has no older rule text
    anywhere in the documents.

**not_in_documents: 6 items, 4 locked; out_of_scope: 3 items, 1 locked.** These refusals are split by question text.
The not_in_documents quota is met. out_of_scope is a standing case (at least 3 items), and it has 3.

**revision_marks: 6 refusals, 4 locked.** Two kinds of page were not used:

- **Blank pages.** The pages marked "intentionally left blank" (Chapter2c p58, pilot report p23) hold no fact to ask
  about.
- **Pages marked draft.** The word "draft" appears in a few documents (01102, 04091, L18, the Signal Timing Manual), but
  I did not use those pages.

I found no strikethrough text or revision bars, but that check was limited. The text-layer survey (`survey.py marks`)
finds markers that are written out in words. Strikethrough and revision bars are not in the text layer, and I saw none
on any of the pages I rendered. I did not render every page to look for them.

**appendix_page: 3 items on 2 pages.** The items are on STEP Appendix B (p39) and TODS Appendix H (p43). The other
appendices are excluded pages, scans already used, or blank figure sheets: TODS Appendices D to G are p36-42, and p40
and p42 are excluded.

## Scorer and schema fit

- `value_matches` does substring matching for any value that is not a single number. Yes/no answers therefore cannot
  be scored, so every such question asks for the value or condition that decides the answer instead. For example, the
  refuge-island question expects "9,000" and the road-diet question expects "20,000 / 25,000".
- Unicode hyphens (U+2010) are not normalized by the scorer. Accept strings use plain hyphens.
- Words for numbers are not normalized to digits: "Forty miles per hour" in L18 is not read as 40 mph. Where the page
  spells the number out, both forms are in `accept` or `all_of`.
- `page_image_read` has no machine check. Those 13 values rest on my reading of the rendered page.
- A clarify item lists 2 branches, even where the page has more conditions.
