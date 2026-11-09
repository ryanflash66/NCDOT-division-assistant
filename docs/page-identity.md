# Page identity: the number printed on each page (DAR-654)

The citation link opens a PDF at `#page=N`, the page's index in the file. Readers quote the number printed on the page instead: PDF page 37 of the TMP Design Manual prints "Page 13", the Utilities Accommodation Manual prints "2-6" and "D-1", MUTCD Part 6 starts at "765". `rag/pages.py` reads that number for every page and `prototype/ingest.py` stores it on each chunk as `printed_page` (a string, or null). When it differs from the index, the chunk's `context` line gets a `printed p.13` segment right after `p.37`.

## How the number is found

1. The PDF's own page label, when the document has labels that run like page numbers and don't just repeat the PDF index. Labels stored as UTF-16 hex (`<FEFF0041>1`) are decoded (`A1`). Labels that equal the index (fhwahop09021, which prints "3-1", "A-2") are used only where no footer or header number is found.
2. Otherwise a number on a text line in the bottom 12% of the page (as displayed, so rotated sheets work), then in the top 12%. Regex families, in order: `Page 13`, `5-13`, `A-3`, roman numerals, a bare integer at the edge of the line.
3. A family only counts for a document when its hits run through the document like page numbers: on at least 3 pages, at least 70% of the steps between hits advance by the page distance (or restart at 1 for a new chapter or appendix), and then a page keeps its number only when it steps in sequence with a neighbouring hit, so body text ending in a number on a page without a footer is not taken. That rejects sign codes repeated on every sheet ("W1-1"), publication numbers, the Standard Specifications' line numbers and drawing sheet numbers that restart with each standard.

## Results over the 60 PDFs

`python -m prototype.page_identity_report` writes `docs/page-identity-report.json`: per document, the page count, labelled pages, pages with a printed number, how many differ from the index, the source counts and five sample pages.

| | |
|---|---|
| documents | 60 (58 indexed; `WZSafety_and_Mobility.pdf` and `Revised Rumble Strip Guidelines.pdf` sit in their folders but aren't in `divisions.py`) |
| pages | 5,924 |
| with a PDF page label | 988 (11 documents) |
| with a printed number | 5,107 (86%): footer 4,145, label 870, header 92 |
| printed number differs from the PDF index | 4,166 |
| documents with no printed number | 17 (scanned chapters, drawings, short memos and forms) |

Spot checks:

| document | PDF page | printed | from |
|---|---|---|---|
| TMP Design Manual | 37 | 13 | footer "Part 2: Chapter 5 \| July 2019\| Page 13" |
| Utilities Accommodation Manual | 3 | ii | footer, under a contents line ending "2-48" |
| Utilities Accommodation Manual | 185 | A-1 | footer (appendix) |
| Transportation Management Plans for Work Zones | 92 | B-10 | footer "Appendix B-10" |
| STEP guide | 1 | A1 | label `<FEFF0041>1`, decoded |
| MUTCD Part 6 | 1 | 765 | label |
| 2024 Standard Specifications | 20 | 1-12 | footer "Section 102 \| 1-12" |
| Division 11 Combined (drawings) | all | none | the sheets carry sign codes ("W21-3") and sheet numbers, no page numbers |

Pages without a printed number keep `printed_page: null`, and the PDF index stays the only page the app cites. The hosted app doesn't read `printed_page` yet (DAR-654 is index-time only).
