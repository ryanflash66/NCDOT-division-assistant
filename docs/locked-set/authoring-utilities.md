# Locked test set: utilities (DAR-653, U4)

`evaluation/locked/utilities.json` holds 80 questions for the `utilities` division: 70 answerable, 10 that must be refused. The schema and split rule are the shared contract in the DAR-652 plan (see `evaluation/locked/README.md` once U1 lands).

## How the items were written

- Every question was written for this set by reading the PDFs in `hosted/documents/utilities/`. None was copied from the dev sets (`eval/*.json`, `evaluation/testset.json`), which stay dev.
- Candidate pages came from the corpus audit (`.handoff/redo-nov4/corpus-audit.json`): pages with tables (`nt > 0`), rotated text (`rotchars / totchars > 0.3`), no text layer (`chars < 10`), and chapter-page or appendix footers.
- **Verification.** For each answerable item the `value` string appears on at least one gold page after normalization (case, quotes, dashes, `$` and thousands commas folded). The text came from pymupdf's text layer (`verified_by: "page_text_match"`, 61 items) or, on pages with no text layer, from RapidOCR at 200 dpi (`verified_by: "ocr_match"`, 9 items). All 9 OCR pages were OCR'd a second time from scratch, and the value was found again each time. Each non-empty `printed_pages` entry was also checked against that page's text.
- **Unanswerable items** (`verified_by: "absent_from_corpus"`) ask about topics the utilities documents don't cover (TODS fees, wind-speed limits, airports, swimming pools, the Blue Ridge Parkway) or about things that don't exist (a Table 3-5 in the UAM, Form R/W 16.8, an inspector hourly rate, an antenna count per pole). A keyword search of the text of all 19 utilities PDFs found nothing that answers any of them. The pole-to-railroad question is a deliberate decoy: `010604.pdf` Table 4-8 gives a vertical clearance above railroad tracks, but neither it nor the UAM gives a horizontal pole-to-track distance.
- `split` is computed in code with the contract rule: `sha1(f"{source}|{pdf_pages[0]}")`, last hex digit < 3 ⇒ `tuning`, else `locked`. Unanswerable items hash the question. That gives 68 locked and 12 tuning items. Rule-based splitting puts fewer than the target 30% in tuning; the split was left as the hash produced it, not rebalanced by hand.
- Askers rotate across divisions (wztc 33, tmsd 30, utilities 17), so most questions come from someone outside Utilities, as the demo expects.

## Page numbering notes

- UAM body pages print chapter-page numbers (`3-28` is PDF p.101). Appendix pages print `A-1`, `C-1`. The front matter is roman (`vi` is PDF p.7). Many appendix pages, including the scanned memos, print no number (`""`).
- DOT Encroachment Submissions User Guide: printed page = PDF page − 1.
- 23 CFR 645 (GovInfo print): printed pages are Federal Register volume pages (`334`, `335`).
- FHWA Program Guide (`if03014.pdf`) Appendix B prints `B-85` on PDF p.85.

## Counts

| type | items | locked | tuning |
|---|---:|---:|---:|
| text | 28 | 25 | 3 |
| table | 14 | 13 | 1 |
| unanswerable | 10 | 7 | 3 |
| scan | 8 | 6 | 2 |
| units | 4 | 2 | 2 |
| figure | 3 | 3 | 0 |
| footnote | 3 | 2 | 1 |
| page_ref | 3 | 3 | 0 |
| rotated | 3 | 3 | 0 |
| cross_ref | 2 | 2 | 0 |
| multipage_table | 2 | 2 | 0 |

Edge cases (an item can carry several):

| edge case | items | locked | tuning |
|---|---:|---:|---:|
| chapter_page | 32 | 26 | 6 |
| appendix_prefix | 19 | 17 | 2 |
| printed_vs_pdf | 18 | 18 | 0 |
| non_first_row | 16 | 15 | 1 |
| table_id | 14 | 11 | 3 |
| near_duplicate | 13 | 12 | 1 |
| form_or_checklist | 11 | 11 | 0 |
| conflicting_values | 10 | 8 | 2 |
| units | 10 | 7 | 3 |
| numeric_precision | 9 | 7 | 2 |
| scan | 9 | 7 | 2 |
| out_of_scope | 8 | 6 | 2 |
| phrasing_drift | 8 | 7 | 1 |
| false_premise | 7 | 5 | 2 |
| conditional | 6 | 4 | 2 |
| landscape | 5 | 4 | 1 |
| merged_header | 5 | 4 | 1 |
| multipage_table | 5 | 5 | 0 |
| non_first_column | 5 | 4 | 1 |
| figure | 4 | 4 | 0 |
| footnote | 4 | 3 | 1 |
| two_page_question | 4 | 4 | 0 |
| cross_ref | 3 | 3 | 0 |
| rotated | 3 | 3 | 0 |
| roman_front_matter | 1 | 1 | 0 |
| toc_decoy | 1 | 1 | 0 |

By document: UAM (`20220713 NCDOT UAM Ver 2-0.pdf`) 49; DOT Encroachment Submissions User Manual 4; 2 each for Form R/W 16.1, 23 CFR 645, the 2026 Cost Reimbursement Guidance, the Encroachment Plan Requirements, `hif22002.pdf` and `utility_row.pdf`; 1 each for Roadway Design Manual ch. 9, the direct-bury poles memo, the 2017 webinar slides, `fhwahop09021.pdf` and `if03014.pdf`; 10 unanswerable. The set covers 66 distinct gold pages, with at most 2 items on any one page.

## Scanned pages (≥ 8 required)

Nine answerable items have a gold page with no text layer: UAM PDF pp. 245, 251, 252, 253, 261, 263, 301 and 304 (Appendix D memos and policies, the Appendix F frac-out plan), plus p.1 of the webinar slides. Item `utilities-070` also accepts scanned p.261 as an alternative to text p.108 (the same 15-day rule appears in both).

## Gaps and choices

- Figure 3-1 (clear zone distances, UAM p.88) is an image table. Two questions on it were dropped because no text layer or OCR text on file confirms their values. They are good candidates once DAR-658 adds figure OCR.
- Fewer than 5 items exist for `rotated` (3; the UAM has few rotated pages with readable values), `cross_ref` (3) and `roman_front_matter` (1). Utilities has no superseded edition pairs and no "Reserved" pages, so matrix rows 18 and 32 are not covered.
- Multi-page tables: utilities has few true continuation tables (the 2026 Cost Reimbursement Guidance definitions table, and the Submissions Guide's Encroachment Lines, Next Action and field tables). Two items (`multipage_table` type) cite both the header page and the continuation page. Three more ask for a row in a table that spans pages, and cite only the page that holds that row.
