# DAR-655: tables (headers, labelled rows, page breaks, flags)

**What changed** (decision log D4 to D6):
- Spanned headers are filled forward and rotated row headers repaired (TMP Design Manual PDF p.37, "Offset (ft)").
- Each table row is also written as labelled text, and a split table repeats its caption and header in every part.
- A table that runs over a page break is joined into one chunk that cites both pages.
- Every table chunk is checked and flagged; the build writes a report per document.

**Merged from:** `ryanflash166/dar-655-table-rows-and-headers` (3334318), `-multipage-table-merge` (c6da8c5), `-table-quality-report` (88f9ed6); main via PR #41 (7489cdf).

## Own check: joining tables over a page break

From `docs/table-merge-check.md`. 20 of the 166 candidate breaks opened by hand: 15 continue, 5 don't.

| rule | continuations found | wrong joins |
|---|---|---|
| first version | 7/15 (25–70%) | 0 of 5 |
| tuned (shipped) | 12/15 (55–93%) | 0 of 5 |

The rule was tuned on the same 20 breaks, so 12/15 is optimistic.

## Own check: table flags

From `docs/build-report-final.json`: 2,773 of 3,815 table chunks carry a flag; 1,717 carry one other than "no caption", mostly empty headers (1,382). Flagged, not fixed.

## Before and after on the locked split

| question type | measure | before | after |
|---|---|---|---|
| table (50) | right page in top 5 | 48/50 (87–99%) | 45/50 (79–96%) |
| | right page first | 35/50 (56–81%) | 41/50 (69–90%) |
| | value right | 47/50 (84–98%) | 48/50 (87–99%) |
| | value and cited page right | 24/50 (35–61%) | 33/50 (52–78%) |
| table over a page break (13) | value right | 13/13 (77–100%) | 12/13 (67–99%) |
| | value and cited page right | 8/13 (36–82%) | 9/13 (42–87%) |
| rotated page (14) | value right | 8/14 (33–79%) | 11/14 (52–92%) |
| | value and cited page right | 6/14 (21–67%) | 6/14 (21–67%) |

The drop in "right page in top 5" for table questions (inside the intervals) is the crowding problem: labelled rows add chunks per table page, and one page can fill 3 of the 5 slots.

**Raw results:** `docs/locked-set/baseline-pre-answers.json`, `docs/locked-set/final.json`; `docs/build-report-final.json`; `docs/table-merge-check.md`.

## Reproduce

```bash
.venv\Scripts\python -m prototype.table_merge_check --out <file>
.venv\Scripts\python -m prototype.ingest --ocr --reuse hosted/index
.venv\Scripts\python -m prototype.build_report --index hosted/index --markdown
```

Commit e7574ac for the locked runs.

## Open

- Crowding of the top 5 by labelled rows (try at most one chunk per page, D9).
- The header-joining rule could turn "Speed | mph" into "Speedmph".
- The flagged tables are not fixed.
