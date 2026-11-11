# DAR-654: printed page next to the PDF page

**What changed.** Every chunk stores the number printed on its page. Citations read "p.13 (PDF page 37)"; the link still opens the PDF at page 37. Page images for the Sources panel are built behind `RENDER_PAGES=1` and are off in production (decision log D2, D3).

**Merged from:** `ryanflash166/dar-654-page-identity-index` (63f1629), `-printed-page-citations` (c3cd239), `-page-images` (9a3b7ec); main via PR #41 (7489cdf).

## Own check: how often a printed number is found

From `docs/page-identity.md` and `docs/page-identity-report.json`, over all 60 PDFs:

| | |
|---|---|
| pages with a PDF page label | 988/5,924 (16–18%) |
| labels that differ from the PDF index | 840/988 (83–87%) |
| pages with a printed number found (label, footer or header) | 5,107/5,924 (85–87%) |
| documents with no printed number | 17 of 60 |

## Before and after on the locked split

| | before | after |
|---|---|---|
| cited printed page right | 0/145 (0–3%) | 84/147 (49–65%) |
| cited PDF page right | 94/185 (44–58%) | 120/190 (56–70%) |
| questions where the printed page differs from the PDF page: value and cited page right | — | 29/52 (42–68%) |

"Before" is 0 because no printed page was shown. The printed-page score is lower than the PDF-page score mostly because a citation must first be on the right PDF page; of the misses, most are answers that cited nothing (see the PR #42 report).

**Raw results:** `docs/locked-set/baseline-pre-answers.json`, `docs/locked-set/final.json` (fields `cited_pages_printed`, `cited_page_ok_printed`); `docs/page-identity-report.json`.

## Reproduce

```bash
.venv\Scripts\python -m prototype.page_identity_report
.venv\Scripts\python -m prototype.ingest --ocr --reuse hosted/index
.venv\Scripts\python -m evaluation.locked.run run --label final --split all --stage all --env-file .env
```

Commit e7574ac.

## Open

- 17 documents print no page number (scanned chapters, drawings, memos); their citations show the PDF page only.
- Page images in production: DAR-665 (bundle size).
