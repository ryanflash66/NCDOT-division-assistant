# DAR-657: caption and table-number field, page aggregation, reranker

**What changed** (decision log D8 to D10):
- A second, boosted keyword field (×1.5) holds captions, table, figure and section numbers, document codes and titles; a number named in the question is boosted ×2. Boost, never filter.
- Ranking whole pages (`PAGE_AGGREGATION`) was tried and left off.
- The reranker now scores text chunks only (`RERANK_TEXT_ONLY=on`); tables keep their search order.

**Merged from:** `ryanflash166/dar-657-caption-id-keyword-field` (a2577a1), `-page-aggregation` (b5884cb), `-reranker-ab` (ab2b0d1); main via PR #41 (7489cdf).

## Variants on the same questions

Options were picked on the tuning split (41 answerable), then each was reported once on the locked split (204 answerable). From `docs/locked-set/reranker-pick.md` and `docs/locked-set/locked-retrieval-*.md`:

| variant | tuning: right page first | locked: right page first | locked: right page in top 5 |
|---|---|---|---|
| MiniLM-L-6, every chunk (old default) | 32/41 (63–88%) | 147/204 (66–78%) | 180/204 (83–92%) |
| no reranker | 31/41 (61–86%) | 136/204 (60–73%) | 183/204 (85–93%) |
| **MiniLM-L-6, text chunks only (shipped)** | **33/41 (66–90%)** | **152/204 (68–80%)** | **183/204 (85–93%)** |
| MiniLM-L-12 | 32/41 (63–88%) | 147/204 (66–78%) | 180/204 (83–92%) |
| page-max aggregation | | 147/204 (66–78%) | 177/204 (81–91%) |
| page-sum aggregation | | 138/204 (61–74%) | 178/204 (82–91%) |

The shipped variant is best on both splits, but inside the intervals: a small gain, not a proven one. bge-reranker-base (too large for the bundle) and jina-turbo (below no reranker on the development sets) were dropped before the locked runs.

**Keyword field, development set** (83 known-page questions, `docs/page-aggregation.md`): right page in top 5 74/83 (81–94%) with keyword search off, 77/83 (85–97%) with it on.

## Before and after on the locked split (whole redo)

| | before | after |
|---|---|---|
| right page first | 144/204 (64–76%) | 152/204 (68–80%) |
| right page in top 5 | 183/204 (85–93%) | 183/204 (85–93%) |
| table number named in the question (24): right page in top 5 | — | 24/24 (86–100%) |

**Raw results:** `docs/locked-set/locked-retrieval-{minilm-l6,none,text-only,minilm-l12,page-max,page-sum}.json`, `docs/reranker-ab.{json,md}`, `docs/keyword-field.md`.

## Reproduce

Each variant is the same command with different settings:

```bash
set RERANK_TEXT_ONLY=on
.venv\Scripts\python -m evaluation.locked.run run --label locked-retrieval-text-only --split locked --stage retrieval
set PAGE_AGGREGATION=max
.venv\Scripts\python -m evaluation.locked.run run --label locked-retrieval-page-max --split locked --stage retrieval
.venv\Scripts\python -m evaluation.rerank_ab --locked tmsd.json --locked utilities.json
```

Commit d60f7d0. `RERANK_MODEL` selects L-12, `RERANK=off` gives the no-reranker run, `RERANK_TEXT_ONLY=off` the old default, and `PAGE_AGGREGATION=sum` the page-sum run (settings in `hosted/divrag/config.py`).

## Open

- Page aggregation with at most one chunk per page is untested and may help the table crowding (DAR-655 report).
- Timings in `docs/reranker-ab.md` were measured on a machine at 100% CPU, so only relative times are given.
