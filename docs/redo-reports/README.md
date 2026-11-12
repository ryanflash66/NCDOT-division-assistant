# Per-ticket reports: the table and figure redo (DAR-652)

One short report per sub-ticket (DAR-660, step 2). Each gives what changed, before and after on the same questions with counts and 95% Wilson intervals, the raw results files, and the command and commit to reproduce it. The overall story is in [`../redo-methods.md`](../redo-methods.md); the decisions and rejected options are in [`../redo-decision-log.md`](../redo-decision-log.md).

**Read this first.** The sub-tickets were merged on one integration branch and measured with one index rebuild and one before/after run (decision log D13). So the locked-set numbers in these reports are the whole redo's effect on each ticket's kind of question, not one ticket alone. Where a ticket had its own check (page numbers found, table joins, reader bake-off, reranker variants), that check is reported too.

| ticket | report | what it is about |
|---|---|---|
| DAR-653 | [dar-653-test-set.md](dar-653-test-set.md) | the locked test set and scorer |
| DAR-654 | [dar-654-page-identity.md](dar-654-page-identity.md) | printed page next to the PDF page; page images |
| DAR-655 | [dar-655-tables.md](dar-655-tables.md) | labelled table rows, headers, tables over a page break, table flags |
| DAR-656 | [dar-656-extraction-bakeoff.md](dar-656-extraction-bakeoff.md) | which PDF reader |
| DAR-657 | [dar-657-search.md](dar-657-search.md) | caption and table-number field, page aggregation, reranker |
| DAR-658 | [dar-658-no-text-pages.md](dar-658-no-text-pages.md) | OCR orientation retry, figure chunks, pages with no text |
| DAR-659 | [dar-659-number-check.md](dar-659-number-check.md) | checking numbers against the cited page |
| PR #42 | [pr-42-citation-fix.md](pr-42-citation-fix.md) | asking uncited answers for their source |
| DAR-662 | [dar-662-refusals.md](dar-662-refusals.md) | why answerable questions were refused; the retry's second look |
| DAR-717 | [dar-717-footnotes.md](dar-717-footnotes.md) | notes under a table kept with the table; a prompt rule for note questions (after the redo, measured on its own) |

**Runs and commits** (all in [`../locked-set/RUNS.md`](../locked-set/RUNS.md)):

| run | commit | index |
|---|---|---|
| `baseline-pre` (retrieval) | d0868dc | pre-redo index, 10,746 chunks (main at 8feefe6) |
| `baseline-pre-answers` | e7574ac | same pre-redo index |
| `final` | e7574ac | redo index, 13,240 chunks |
| `locked-retrieval-*` (reranker and aggregation variants) | d60f7d0 | redo index |
| `tuning-final2`, `tuning-cite2`, `tuning-cite2-k8` | 3d0adb9 | redo index |

The integration branch merged into main as PR #41 (7489cdf).
