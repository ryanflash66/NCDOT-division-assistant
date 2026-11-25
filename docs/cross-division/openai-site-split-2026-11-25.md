# All divisions (DAR-666): openai-site-split-2026-11-25

Commit `fae1784`, 2026-11-25T10:32:26+00:00, models gpt-6.1-terra, nvidia/nemotron-3-ultra-550b-a55b:free, nvidia/nemotron-3.5-super-vl:free, google/gemma-4-31b-it:free; ALL_DIVISIONS_TOP_K 8, ALL_DIVISIONS_CANDIDATES 40, TOP_K 5. Development questions only (the locked set's tuning split); see `evaluation/cross_division/run.py`.

Answers from a CLI preview of `fae1784` on Vercel, OpenAI answering (the production setup); the same questions as `free-models-split-2026-11-24`. The pairs' baseline without the split is `openai-site-joined-2026-11-25` (a preview of `cac180a`). `/api/ask` returns no passages or token counts, so those cells are blank; the passages don't depend on the model, so the free-model reports' passage counts hold (13/24 parts' gold pages before the split, 21/24 after).

## What this shows

- **The split holds with OpenAI.** Both parts right went from 2/12 (unsplit preview) to 10/12, both citing their gold page from 2 to 9, parts right from 13/24 to 22/24, answers citing two divisions from 3/12 to 11/12. Same as with the free models (3 to 10).
- **The same two pairs miss:** x-01's cone-base share (wztc-037), where OpenAI says the documents don't give it, and x-11's tmsd-003, which takes 345 ft from a WZTC manual instead of TMSD's 330, as tmsd-003 alone does with All divisions.
- **One-division questions lose little to All divisions with OpenAI:** value right 39/41 against 40/41, citing the gold page 38/41 both ways, no confident wrong answers either way (free models: 2 for All divisions). tmsd-003 asked alone of All divisions is refused here rather than answered wrong; wztc-043 is refused both ways.
- **Time on Vercel:** rerank 1.7 s for one division and for All divisions (40 candidates either way), and 1.9 s for the split pairs against 2.4 s unsplit, so splitting costs no rerank time. Mean total 4.8 s for one division, 6.3 s for All divisions, 7.6 s for a split pair against 7.4 s unsplit.
- **Cost is only an upper bound:** the ledger rose $2.17 over these 108 questions and $0.36 over the 12 unsplit ones, but another run (DAR-739) used the same ledger at the same time, so $0.02 per question is the most it could be, not a measurement.

## Cross-division questions (two divisions in one question, asked of All divisions)

| | count |
|---|---|
| both parts' values right | 10/12 |
| both right, each citing its gold page | 9/12 |
| only one part right | 2/12 |
| refused | 0/12 |
| parts with the right value | 22/24 |
| parts whose gold page was in the first passages (before any second look) | - |
| answers citing two or more divisions | 11/12 |

## One-division questions asked of their division and of All divisions

| | own division | All divisions |
|---|---|---|
| value right | 40/41 | 39/41 |
| value right, citing the gold page | 38/41 | 38/41 |
| confident wrong | 0/41 | 0/41 |
| answerable but refused | 1/41 | 2/41 |
| gold page in the first passages | - | - |
| must-refuse questions answered | 0/7 | 0/7 (read below: another division may cover them) |

## Time and cost per question (Vercel, https://ncdot-division-assistant-90ebjl3aj-ncdot.vercel.app; its models answered)

| | own division | All divisions |
|---|---|---|
| questions | 48 | 60 |
| total s, mean | 4.8 | 6.3 |
| total s, median | 4.3 | 6.2 |
| retrieval s, mean | 1.8 | 1.8 |
| rerank s, mean | 1.7 | 1.7 |
| passages the model read, mean | - | - |
| model calls, mean | - | - |
| input tokens, mean (estimated) | - | - |
| output tokens, mean (estimated) | - | - |
| OpenAI $ per question (estimated) | - | - |

OpenAI spend on the site's ledger during the run: $2.1652 for 108 questions asked (the ledger is shared with live traffic; estimated from token usage, not billed).

## Every cross-division question

| id | parts | value | cited | in passages | divisions cited |
|---|---|---|---|---|---|
| x-01 | wztc-037 + utilities-026 | no yes | no yes | - - | utilities |
| x-02 | wztc-041 + utilities-018 | yes yes | no yes | - - | utilities, wztc |
| x-03 | wztc-045 + utilities-029 | yes yes | yes yes | - - | utilities, wztc |
| x-04 | wztc-009 + utilities-043 | yes yes | yes yes | - - | utilities, wztc |
| x-05 | wztc-016 + tmsd-056 | yes yes | yes yes | - - | tmsd, wztc |
| x-06 | wztc-067 + tmsd-061 | yes yes | yes yes | - - | tmsd, wztc |
| x-07 | wztc-005 + tmsd-043 | yes yes | yes yes | - - | tmsd, wztc |
| x-08 | wztc-030 + tmsd-038 | yes yes | yes yes | - - | tmsd, wztc |
| x-09 | utilities-001 + tmsd-004 | yes yes | yes yes | - - | tmsd, utilities, wztc |
| x-10 | utilities-063 + tmsd-074 | yes yes | yes yes | - - | tmsd, utilities |
| x-11 | utilities-019 + tmsd-003 | yes no | yes no | - - | utilities, wztc |
| x-12 | utilities-002 + tmsd-034 | yes yes | yes yes | - - | tmsd, utilities |
