# DAR-658: scans, drawings and sideways pages

**What changed** (decision log D11):
- OCR reads the page in the orientation its text layer suggests, and reads the other three when confidence is low or much of the text is sideways (`rag/ocr.py`). Low-confidence and rotated readings are flagged (17 chunks).
- Each figure caption gets its own chunk: the caption, nearby lines and the drawing's OCR labels. No generated descriptions (a vision model needs Dr. Namian's approval).

**Merged from:** `ryanflash166/dar-658-ocr-orientation-figures` (abdcd4d); main via PR #41 (7489cdf).

## Before and after on the locked split

| question type | measure | before | after |
|---|---|---|---|
| figure (13) | right page first | 8/13 (36–82%) | 11/13 (58–96%) |
| | right page in top 5 | 12/13 (67–99%) | 13/13 (77–100%) |
| | cited PDF page right | 4/11 (15–65%) | 10/12 (55–95%) |
| | value and cited page right | 4/13 (13–58%) | 10/13 (50–92%) |
| scanned page (14) | right page in top 5 | 13/14 (69–99%) | 13/14 (69–99%) |
| | value right | 13/14 (69–99%) | 13/14 (69–99%) |
| | value and cited page right | 5/14 (16–61%) | 5/14 (16–61%) |
| rotated page (14) | right page in top 5 | 9/14 (39–84%) | 10/14 (45–88%) |
| | value right | 8/14 (33–79%) | 11/14 (52–92%) |

Figures improved the most of any type, though the intervals still overlap. Scans did not change: the right page was already found, and the misses are citation misses (see PR #42).

## Own check: pages still without text

From `docs/no-text-pages.md`, regenerated against the final index with the pre-redo index as baseline: 6 image-only pages (5 blank scans, 1 photo page) and 5 text-loss pages (4 tables with rotated headers or a form, 1 sideways map legend). The redo fixed none of them; no page lost its text. The ticket comment's earlier "32 image-only and 7 text-loss" was counted against an older index and is corrected in the decision log.

**Raw results:** `docs/locked-set/baseline-pre-answers.json`, `docs/locked-set/final.json`, `docs/no-text-pages.md`.

## Reproduce

```bash
.venv\Scripts\python -m prototype.ingest --ocr --reuse hosted/index
.venv\Scripts\python -m prototype.no_text_pages --baseline <pre-redo index> --index hosted/index
```

Commit e7574ac for the locked runs; `no_text_pages.py` as fixed in PR #44 (abde63d).

## Open

- The 4 rotated-header pages and the map legend need a text-layer fix, not OCR.
- Drawings with values only in the image need a vision model (Dr. Namian's decision).
