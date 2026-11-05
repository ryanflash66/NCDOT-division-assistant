# Locked test set: how the `wztc` questions were written (DAR-653)

`evaluation/locked/wztc.json` holds 100 questions for the Work Zone Traffic
Control division: 90 answerable from one page (or a pair of pages) of the wztc
documents, and 10 that the documents do not answer and must be refused. The
schema is the shared one from the scorer unit of DAR-653 (`evaluation/locked/README.md`
and `normalize.py` on branch `ryanflash166/dar-653-locked-set-scorer`, which
this file is merged next to). The split rule, repeated here so it can be
checked from this file alone:
`int(sha1(f"{source}|{pdf_pages[0]}").hexdigest()[-1], 16) < 3` gives
`tuning`, otherwise `locked`; refusals hash on the question text.

## How each item was made

1. Candidate pages came from the corpus audit
   (`.handoff/redo-nov4/corpus-audit.json`): pages with tables (`nt > 0`),
   rotated text (`rotchars/totchars > 0.3`), landscape pages, tables that run
   on (`tabbot` then `tabtop`, `cont`), pages with no text layer (`chars < 10`)
   and pages whose printed number differs from the PDF index.
2. The question was written from the page itself. The development sets
   (`eval/*.json`, `evaluation/testset.json`) were read only to steer away from
   them: where a dev question uses a table (TMP pp.37-38 deflections, Table 3-2
   at 1640 ft / 950 ft, Figure 16-18 clear zones, run-out lengths, flare rates
   at 55 mph, the Florida/California/West Virginia drop-off rows), the locked
   item asks a different cell or a different table.
3. The value was checked by script against the page: the expected `value`
   must be found, after the shared number/unit normalization
   (`normalize.py`, `value_matches`, from the scorer branch), in the text layer of the
   first gold page (`verified_by: page_text_match`), or in RapidOCR text of that
   page for scans (`ocr_text_match`). For scans the script also confirmed the
   value is *not* in the text layer, so those items really test the OCR path.
4. Rotated drawings and sideways tables (Division 11 sheets 1101.11, Spec
   Table 1080-2, the Work Zone Safety and Mobility guidelines owners table) scramble cell order in the
   text layer, so their cells were also read off the rendered page before the
   text check.
5. `printed_pages` were computed, not typed: the PDF page label when the file
   has labels (MUTCD Part 6, Best Practices Guidebook, the 2025 memo), the
   `Page N` header for the TMP manual (chapter-relative, so "5" can mean many
   PDF pages), the `11-3`-style header for the Standard Specifications, the
   folio line for the FHWA reports and the CFR, the OCR folio for scans, and
   `""` for the Division 11 standard drawings and the one-page significance
   chart, which print none.
6. `split` was computed with the shared hash rule; nothing was moved by hand.

Unanswerable items were checked by searching the text of every wztc document
(and the OCR text of the scanned chapters) for the topic. Three are in-domain
traps: a cell beyond the range of a table that exists (90 mph on the NC-PCB
tables, 85 mph on RSD 1101.11 sheet 2), and one asks for a year the process
review does not cover (2024 fatalities; it reports 2023).

## Counts

100 items: 80 `locked`, 20 `tuning`; 10 refusals.

| type | n | | type | n |
|---|---|---|---|---|
| table | 11 | | footnote | 8 |
| table_id | 5 | | units | 6 |
| multipage_table | 7 | | page_ref | 7 |
| rotated | 11 | | duplicate_pages | 5 |
| scan | 9 | | cross_ref | 5 |
| figure | 5 | | text | 11 |
| unanswerable | 10 | | | |

| edge case | n | edge case | n |
|---|---|---|---|
| rotated_text | 15 | printed_vs_pdf_page | 7 |
| non_first_row_col | 12 | continuation_page | 7 |
| landscape | 8 | near_identical_tables | 6 |
| merged_header | 8 | two_page_gold | 6 |
| scanned_page | 8 | cross_reference | 5 |
| table_caption_named | 5 | out_of_scope | 5 |
| table_note | 4 | chapter_page_number | 3 |
| figure_callout | 3 | footnote_defines_column | 2 |
| metric_units | 2 | unit_of_measure | 2 |
| beyond_table_range | 2 | other_state | 2 |
| image_table, multi_row_header, near_identical_rows, ratio_value, figure_notes, screenshot, footnote_changes_value, page_footnote, unit_conversion, currency_rate, precision, numeric_weight, year_not_covered | 1 each | | |

Documents used (answerable items): TMP Design Manual 19, MUTCD Part 6 16,
FHWA road user costs (FHWA-HOP-12-005) 16, Standard Specifications 6,
Chapter 2 (scans) 6, Division 11 drawings 5, Chapter 5 (scans) 4, Work Zone Safety and Mobility
guidelines 3, and 1-2 each from the CFR, Best Practices Guidebook, SOP 10-9,
the 2025 positive protection memo, the 2023 process review, the 2004 final
rule, the rule guide, the WZ impacts guide, the ITS guide and the level of
significance chart.

## Things to know when scoring

- Short values (`5` for Table 9-1 in metres, `30` for the 60-70 mph clear
  zone, `1.4`) are matched as numbers, so they only count when the answer
  states that number; the page check for them is weaker than for longer values.
- Two-page golds list the page holding the value first; the split hashes on
  that page. `duplicate_pages` item wztc-074 (impact angle) has the same value
  on both tables, so either page is right.
- Several values carry the PDF's own spelling (`19 : 1`, `12 ft. 10 in.`,
  `Seventy percent`); `accept` holds the usual answer spellings.
- The TMP manual's detour example computes a left turn as 0.7 although the
  rule says 0.5; item wztc-081 asks for the rule (0.5).
