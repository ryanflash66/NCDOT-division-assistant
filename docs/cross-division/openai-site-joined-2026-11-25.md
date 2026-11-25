# All divisions (DAR-666): openai-site-joined-2026-11-25

Commit `cac180a`, 2026-11-25T10:10:42+00:00, models gpt-6.1-terra, nvidia/nemotron-3-ultra-550b-a55b:free, nvidia/nemotron-3.5-super-vl:free, google/gemma-4-31b-it:free; ALL_DIVISIONS_TOP_K 8, ALL_DIVISIONS_CANDIDATES 40, TOP_K 5. Development questions only (the locked set's tuning split); see `evaluation/cross_division/run.py`.

The two-part questions only, from a CLI preview of `cac180a` (All divisions before the split) with OpenAI answering: the baseline for `openai-site-split-2026-11-25`, where they are compared. The one-division tables are empty because only the pairs were asked.

## Cross-division questions (two divisions in one question, asked of All divisions)

| | count |
|---|---|
| both parts' values right | 2/12 |
| both right, each citing its gold page | 2/12 |
| only one part right | 9/12 |
| refused | 0/12 |
| parts with the right value | 13/24 |
| parts whose gold page was in the first passages (before any second look) | - |
| answers citing two or more divisions | 3/12 |

## One-division questions asked of their division and of All divisions

| | own division | All divisions |
|---|---|---|
| value right | - | - |
| value right, citing the gold page | - | - |
| confident wrong | - | - |
| answerable but refused | - | - |
| gold page in the first passages | - | - |
| must-refuse questions answered | - | - (read below: another division may cover them) |

## Time and cost per question (Vercel, https://ncdot-division-assistant-3p93q25sd-ncdot.vercel.app; its models answered)

| | own division | All divisions |
|---|---|---|
| questions | 0 | 12 |
| total s, mean | - | 7.4 |
| total s, median | - | 7.4 |
| retrieval s, mean | - | 2.5 |
| rerank s, mean | - | 2.4 |
| passages the model read, mean | - | - |
| model calls, mean | - | - |
| input tokens, mean (estimated) | - | - |
| output tokens, mean (estimated) | - | - |
| OpenAI $ per question (estimated) | - | - |

OpenAI spend on the site's ledger during the run: $0.3612 for 12 questions asked (the ledger is shared with live traffic; estimated from token usage, not billed).

## Every cross-division question

| id | parts | value | cited | in passages | divisions cited |
|---|---|---|---|---|---|
| x-01 | wztc-037 + utilities-026 | no no | no no | - - | utilities |
| x-02 | wztc-041 + utilities-018 | yes no | yes no | - - | wztc |
| x-03 | wztc-045 + utilities-029 | yes no | yes no | - - | wztc |
| x-04 | wztc-009 + utilities-043 | yes no | yes no | - - | wztc |
| x-05 | wztc-016 + tmsd-056 | yes yes | yes yes | - - | tmsd, wztc |
| x-06 | wztc-067 + tmsd-061 | yes no | yes no | - - | wztc |
| x-07 | wztc-005 + tmsd-043 | yes yes | yes yes | - - | tmsd, wztc |
| x-08 | wztc-030 + tmsd-038 | yes no | yes no | - - | wztc |
| x-09 | utilities-001 + tmsd-004 | yes no | yes no | - - | utilities |
| x-10 | utilities-063 + tmsd-074 | yes no | yes no | - - | utilities |
| x-11 | utilities-019 + tmsd-003 | yes no | yes no | - - | utilities, wztc |
| x-12 | utilities-002 + tmsd-034 | yes no | yes no | - - | utilities |
