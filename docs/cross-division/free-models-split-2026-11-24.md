# All divisions (DAR-666): free-models-split-2026-11-24

Commit `cac180a`, 2026-11-25T01:04:09+00:00, models nvidia/nemotron-3-ultra-550b-a55b:free, nvidia/nemotron-3.5-super-vl:free, google/gemma-4-31b-it:free; ALL_DIVISIONS_TOP_K 8, ALL_DIVISIONS_CANDIDATES 40, TOP_K 5. Development questions only (the locked set's tuning split); see `evaluation/cross_division/run.py`. Run on `cac180a` with the question split (`divrag/query.py` `split_parts`) not yet committed; it is the commit after it.

## What this shows

- **Splitting a two-part question fixes most of what `free-models-2026-11-24` lost.** Both parts right went from 3/12 to 10/12 (both citing their gold page: 3 to 9), the second part's value from 3/12 to 11/12, and every answer now cites both divisions (4/12 before). The parts' gold pages reached the first passages in 21 of 24 parts, against 13.
- **What is still wrong:** x-01's first part (the cone-base share, wztc-037) lost its page, which the joined question had only reached on the second look; x-11's second part is tmsd-003, which All divisions also gets wrong asked alone (a WZTC document's 345 ft instead of TMSD's 330).
- **One-division questions are unchanged:** none of the locked set's questions (all splits) is split, so their All-divisions answers are the cached ones from the earlier run and their table is the same.
- **Cost:** the parts share the 40 reranked candidates (20 each), so the rerank costs the same: 0.58 s whole against 0.56 s split, timed back to back on the 12 pairs locally (the run's own 0.32 s against 0.71 s was the machine's load). Embedding twice adds 0.02 s. The model reads slightly fewer input tokens (9,771 against 11,249 per pair, estimated) and writes more (292 against 219), since it now answers both parts. The pairs' mean time rose from 6.0 s to 9.6 s, all in the free models' answer time.

## Cross-division questions (two divisions in one question, asked of All divisions)

| | count |
|---|---|
| both parts' values right | 10/12 |
| both right, each citing its gold page | 9/12 |
| only one part right | 2/12 |
| refused | 0/12 |
| parts with the right value | 22/24 |
| parts whose gold page was in the first passages (before any second look) | 21/24 |
| answers citing two or more divisions | 12/12 |

## One-division questions asked of their division and of All divisions

| | own division | All divisions |
|---|---|---|
| value right | 40/41 | 38/41 |
| value right, citing the gold page | 36/41 | 31/41 |
| confident wrong | 0/41 | 2/41 |
| answerable but refused | 1/41 | 1/41 |
| gold page in the first passages | 40/41 | 39/41 |
| must-refuse questions answered | 0/7 | 0/7 (read below: another division may cover them) |

## Time and cost per question (local CPU; free models answered, cost priced at gpt-6.1-terra (1.0, 5.0))

| | own division | All divisions |
|---|---|---|
| questions | 48 | 60 |
| total s, mean | 5.3 | 8.0 |
| total s, median | 2.5 | 5.7 |
| retrieval s, mean | 0.3 | 0.4 |
| rerank s, mean | 0.3 | 0.4 |
| passages the model read, mean | 3.4 | 6.4 |
| model calls, mean | 1.6 | 2.1 |
| input tokens, mean (estimated) | 6739.9 | 11406.5 |
| output tokens, mean (estimated) | 35.8 | 142.5 |
| OpenAI $ per question (estimated) | 0.00692 | 0.01212 |

## Every cross-division question

| id | parts | value | cited | in passages | divisions cited |
|---|---|---|---|---|---|
| x-01 | wztc-037 + utilities-026 | no yes | no yes | no yes | utilities, wztc |
| x-02 | wztc-041 + utilities-018 | yes yes | no yes | no yes | utilities, wztc |
| x-03 | wztc-045 + utilities-029 | yes yes | yes yes | yes yes | utilities, wztc |
| x-04 | wztc-009 + utilities-043 | yes yes | yes yes | yes yes | utilities, wztc |
| x-05 | wztc-016 + tmsd-056 | yes yes | yes yes | yes yes | tmsd, wztc |
| x-06 | wztc-067 + tmsd-061 | yes yes | yes yes | yes yes | tmsd, wztc |
| x-07 | wztc-005 + tmsd-043 | yes yes | yes yes | yes yes | tmsd, wztc |
| x-08 | wztc-030 + tmsd-038 | yes yes | yes yes | yes yes | tmsd, wztc |
| x-09 | utilities-001 + tmsd-004 | yes yes | yes yes | yes yes | tmsd, utilities |
| x-10 | utilities-063 + tmsd-074 | yes yes | yes yes | yes yes | tmsd, utilities |
| x-11 | utilities-019 + tmsd-003 | yes no | yes no | yes no | utilities, wztc |
| x-12 | utilities-002 + tmsd-034 | yes yes | yes yes | yes yes | tmsd, utilities |
