# All divisions (DAR-666): free-models-2026-11-24

Commit `37144ba`, 2026-11-24T23:17:46+00:00, models nvidia/nemotron-3-ultra-550b-a55b:free, nvidia/nemotron-3.5-super-vl:free, google/gemma-4-31b-it:free; ALL_DIVISIONS_TOP_K 8, ALL_DIVISIONS_CANDIDATES 40, TOP_K 5. Development questions only (the locked set's tuning split); see `evaluation/cross_division/run.py`.

## What this shows

- **Two questions in one mostly lose the second.** Both parts were right in 3 of 12; the first part was right in all 12, the second in 3. The second part's gold page reached the model in 2 of 12 (x-01 found both only on the second look): one embedding of the joined question ranks the first question's pages above the second's. Splitting a multi-part question and searching each part is the obvious fix; not done here (follow-up).
- **A one-division question asked of All divisions costs a little accuracy.** Value right 38/41 against 40/41, and 2 confident wrong answers against 0: tmsd-003 answered 345 ft from a WZTC document instead of TMSD's 330 (another division's document giving another number for a similar case), and tmsd-004 read the wrong row of the right table. Citing the gold page fell from 36 to 31, partly free-model noise (tmsd-038 went the other way).
- **Time and cost:** about 2 s more per question locally (mean 7.3 s against 5.3 s; retrieval and rerank 0.3 s either way, since 40 merged candidates are reranked as for one division). On Vercel the rerank of 40 took about 5.4 s for one division and should be the same for all. The model reads 6.3 passages against 3.4 and makes 2.1 calls against 1.6, so about 1.2 cents per question on OpenAI's `gpt-6.1-terra` against 0.7 (estimated from the prompt length, not billed).
- The free models' rate limits (504s) failed some retries, which then kept the refusal: the same for both columns.

## Cross-division questions (two divisions in one question, asked of All divisions)

| | count |
|---|---|
| both parts' values right | 3/12 |
| both right, each citing its gold page | 3/12 |
| only one part right | 9/12 |
| refused | 0/12 |
| parts with the right value | 15/24 |
| parts whose gold page was in the first passages (before any second look) | 13/24 |
| answers citing two or more divisions | 4/12 |

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
| total s, mean | 5.3 | 7.3 |
| total s, median | 2.5 | 5.3 |
| retrieval s, mean | 0.3 | 0.3 |
| rerank s, mean | 0.3 | 0.3 |
| passages the model read, mean | 3.4 | 6.3 |
| model calls, mean | 1.6 | 2.1 |
| input tokens, mean (estimated) | 6739.9 | 11702.1 |
| output tokens, mean (estimated) | 35.8 | 127.8 |
| OpenAI $ per question (estimated) | 0.00692 | 0.01234 |

## Every cross-division question

| id | parts | value | cited | in passages | divisions cited |
|---|---|---|---|---|---|
| x-01 | wztc-037 + utilities-026 | yes yes | yes yes | no no | utilities, wztc |
| x-02 | wztc-041 + utilities-018 | yes no | yes no | yes no | wztc |
| x-03 | wztc-045 + utilities-029 | yes no | yes no | yes no | wztc |
| x-04 | wztc-009 + utilities-043 | yes no | yes no | yes no | wztc |
| x-05 | wztc-016 + tmsd-056 | yes yes | yes yes | yes yes | tmsd, wztc |
| x-06 | wztc-067 + tmsd-061 | yes no | yes no | yes no | wztc |
| x-07 | wztc-005 + tmsd-043 | yes yes | yes yes | yes yes | tmsd, wztc |
| x-08 | wztc-030 + tmsd-038 | yes no | yes no | yes no | wztc |
| x-09 | utilities-001 + tmsd-004 | yes no | yes no | yes no | utilities |
| x-10 | utilities-063 + tmsd-074 | yes no | yes no | yes no | utilities |
| x-11 | utilities-019 + tmsd-003 | yes no | yes no | yes no | utilities, wztc |
| x-12 | utilities-002 + tmsd-034 | yes no | yes no | yes no | utilities |
