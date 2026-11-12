# Held-out set: authoring notes for `wztc` (Work Zone Traffic Control)

File: `evaluation/heldout/wztc.json`, 100 items (91 locked, 9 tuning). Written to
`.handoff/dar-661/AUTHORING-BRIEF.md`. Helper scripts are in `.handoff/dar-661/wztc/` (not committed).
`items.py` holds the item definitions and `build.py` verifies them and writes the JSON.

## How candidates were chosen

- **Documents.** The source list is `hosted/divrag/divisions.py` (20 wztc documents). `hosted/documents/wztc/` holds 21 PDFs.
  `WZSafety_and_Mobility.pdf` is not listed in `divisions.py`, so it is never a source.
- **Unusable documents.** Three documents have every page in `.handoff/dar-661/exclude-pages.json`: GLWZSIG,
  SOP 10-9 and the PPD memo. None of their pages is gold. The other 17 documents each have at least one item.
- **Finding candidate pages.**
  - Per-page view of `.handoff/redo-nov4/corpus-audit.json` (`aud.py`): chars, images, rotation, tables, `cont`, `reserved`.
  - Text dumps of every page (`dump.py`), and RapidOCR text for the image-only MUTCG chapters (`ocr.py`).
  - List-over-page-break finder (`lists.py`).
  - Cross-division shingle comparison (`dup.py`, `dupchk.py`) for `duplicate_section`.
  - Every table, drawing, rotated page and scanned page used was rendered to PNG (`r.py`) and read on the image.
    This covers D11 p40 and p47, MUTCD Figure 6L-3, the TMPG Table B.1 pages, RUC Tables 21 and 37 and the Example 2.2 table,
    Spec Table 1205-5, Guidelines Table 2, and MUTCG Ch. 2/5 pages.
- **Page rules.**
  - No gold page is excluded.
  - No page has more than 2 items; most have 1.
  - The split comes from `evaluation.locked.split_of`. Pages were never moved to change a split.
- **Askers.** 62 `utilities`, 32 `tmsd`, 6 `wztc` (6%).
- **Competing answers.** Where two division documents give different values, the question names the document and both
  sides are tagged `conflicting_documents`:
  - short duration: MUTCD 1 hour vs MUTCG 30 minutes;
  - freeway cones: MUTCD 28 in vs RSD 36 in;
  - vehicle-mounted arrow boards: MUTCD "as high as practicable" vs MUTCG 7 ft.

## Verification

`build.py` checks every item before writing:

- **Answerable items.** `value_matches(value, accept, text)` on a gold page's text layer (`page_text_match`).
  - OCR items (`ocr_text_match`) are checked on the RapidOCR text instead, and the value must be absent from the text layer.
  - D11 p40 chart: the text layer has the bare numbers (the unit is in the header "(FEET)±"). These two items are
    `page_image_read`; the script checks the bare number and the unit was read on the image.
  - Each `all_of` part must be on a gold page.
- **Printed pages.** The printed page must be the PDF label or appear on the page (text or OCR).
  - One exception: Chapter_5 p11's folio "76" was read on the image, because OCR merged it into the heading ("765.2.4").
- **Refusals.** Each absence regex is run, whitespace-collapsed and case-insensitive, over every page of all 20
  documents plus the Chapter_2/Chapter_5 OCR text, and must have zero hits. The patterns are in `items.py`. The note of
  each refusal says what was checked.
- **False premises.** The script checks that the wrong value in the premise is not accepted by `value_matches`.
- **Validation.** `.venv\Scripts\python -m evaluation.heldout.run validate` passes.

## Printed-page conventions

| Document | Printed page convention |
|---|---|
| TMP Design Manual | "Page N" within each chapter |
| MUTCD part6 | PDF label = PDF page + 764 |
| MUTCG Chapter_2 | folio = PDF page + 6 |
| CFR | header page 245 and up |
| FR | 54562 and up |
| rule_guide, wzi_guide, trans_mgmt_plans | chapter-page or appendix folios (5-8, 3-13, A-10, B-6) |
| bpguidebook | PDF labels |
| Division 11 drawings | "" (they print drawing numbers, not page numbers) |
| NCDOTFinalRuleImplementation | "" (no folios) |
| Technical report documentation forms | "" (no folios) |

## Counts

**Behaviour:** answer 77, refuse 13, clarify 5, correct 5.

**Type:** text 64, unanswerable 13, scan 6, table 5, rotated 3, figure 3, footnote 3, multipage_table 3.

**Priority tags** (total / locked / distinct gold pages):

| Tag | Total | Locked | Pages |
|---|---|---|---|
| range_threshold | 10 | 9 | 10 |
| conditional | 7 | 7 | 6 |
| superseded | 5 | 5 | 5 |
| multi_column | 9 | 7 | 8 |
| symbols | 6 | 6 | 6 |
| not_in_documents | 5 | 4 | 5 |
| false_premise | 5 | 5 | 5 |
| duplicate_section | 6 | 5 | 6 |
| toc_decoy | 5 | 5 | 5 |
| list_page_break | 5 | 4 | 5 |
| missing_variable | 5 | 5 | 5 |
| revision_marks | 6 | 5 | 6 |
| degraded_scan | 0 | 0 | 0 (absent, see below) |

**Standing tags** (total / locked):

| Tag | Total | Locked |
|---|---|---|
| printed_vs_pdf | 5 | 4 |
| chapter_page | 5 | 5 |
| appendix_page | 4 | 4 |
| near_identical | 6 | 6 |
| not_first_row_col | 6 | 5 |
| multipage_table | 3 | 3 |
| merged_header | 3 | 3 |
| rotated | 4 | 4 |
| scan | 6 | 5 |
| footnote | 3 | 2 |
| units | 9 | 7 |
| cross_reference | 3 | 3 |
| two_pages | 5 | 4 |
| conflicting_documents | 6 | 5 |
| figure | 3 | 3 |
| form | 3 | 3 |
| out_of_scope | 3 | 3 |
| precision | 5 | 4 |
| rephrased | 10 | 9 |
| table_id | 12 | 12 |

## Cases that are absent or thin, and how that was checked

- **`degraded_scan`: absent (0 items).**
  - Image-only pages exist only in `Chapter_2.pdf` and `Chapter_5.pdf` (42 pages). The audit showed `chars=0` with images; the
    low-char pages in other documents are blank or separator pages.
  - All 42 pages were viewed on a contact sheet (`sheet.py` -> `img/scan_sheet.png`). Ch2 p16, Ch2 p22 and Ch5 p5 were
    also viewed at higher zoom.
  - They are clean, upright digital exports built from tiled images (about 300 dpi; tile transform 760 px over 182 pt). There is
    no skew, stamp, speckle, low resolution or handwriting, so they are tagged `scan` only.
- **`superseded`: the division holds few real version pairs.**
  - CFR 2024 Subpart J was diffed against the 2004 FR rule text: the rule text is the same, so that pair gave no item.
  - Items used:
    - `rule_guide` "Former Rule / Updated Rule" comparisons (p21-23);
    - the 2023 process review (MASH replacing NCHRP 350);
    - the 2004 FR's account of the proposed wording "roadside safety features" changing to "hardware" in the final rule.
  - The MUTCG skinny-drum transition note (Ch2 p28) was not used: it is a transition rule inside one document, not two versions.
- **`revision_marks`: "[Reserved]" occurs only in CFR part 630.**
  - Reserved sections: Subpart C, Subparts E-F, 630.707, Subpart I. Four refusals ask about them.
  - One answer item uses live text on the page with Subparts E-F [Reserved].
  - One refusal uses the Guidelines' "Assessment Requirements During/After Construction - To Be Developed" placeholder.
  - A grep for strikethrough, revision bars and draft watermarks found none.
- **`list_page_break`.** Chosen from the `lists.py` hits after reading both pages. TMP 123-124 and wzi 8-9 are false hits:
  a new list starts on the next page.

## Schema / scorer notes

- **Short or unit-carrying values match as substrings.** Values are chosen with that in mind:
  - The CFR "AC" project-number prefix was dropped, because "ac" would match nearly any answer.
  - The Spec temperatures keep the degree glyph, with "50 degrees" / "50 deg" as alternatives, because the normalizer does not
    rewrite "50°F" (the "F" blocks the degree rule).
- **Unicode fraction glyphs.** The MUTCD shoulder-taper "¹⁄3 L" uses a superscript-one plus U+2044. `normalize` does not
  map these, so "1/3 L" is the value and the glyph form is in `accept`.
- **Chart numbers without units.** For drawing charts whose unit is only in a header, the text layer has bare numbers.
  The unit-bearing value can only be confirmed on the image (`page_image_read`).
- **Refusals are split by question hash, not by page.** The "pages" count for refusal-only tags therefore counts questions.
