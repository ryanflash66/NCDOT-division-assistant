# DAR-659: checking the numbers in an answer

**What changed** (decision log D12). Every number with its unit in an answer must appear in the passages the answer cites, after normalising commas, fractions and unit spellings (`hosted/divrag/verify.py`). A missing number triggers one more ask; if it is still missing, the answer is shown with an "unverified" warning.

**Merged from:** `ryanflash166/dar-659-number-guardrail` (bc1ad0c); main via PR #41 (7489cdf).

## Before and after on the locked split

| | before | after |
|---|---|---|
| cited answers flagged "unverified" | 1/110 (0–5%) | 2/132 (0–5%) |
| flags that were false alarms (the value was right) | 1/104 (0–5%) | 2/124 (0–6%) |
| wrong value shown with a citation | 6/232 (1–6%) | 8/232 (2–7%) |
| of those, flagged by the check | 0 of 6 | 0 of 8 |

The "before" run used the same answering code, so the check also ran there. Over both runs the check flagged no wrong answer. In all 8 confident wrong answers the wrong number is printed on the cited page: the model read the wrong cell or row of the right table. The check catches made-up numbers, not misread tables.

**Other checks:** a test with a deliberately wrong number is caught (`tests/test_hosted_numbers.py`), and the turn-radius question was answered right 3 of 3 times against the running app.

**Raw results:** `docs/locked-set/baseline-pre-answers.json`, `docs/locked-set/final.json` (fields `unverified`, `flagged`, `false_flag`, `critical`).

## Reproduce

```bash
.venv\Scripts\python -m pytest tests/test_hosted_numbers.py
.venv\Scripts\python -m evaluation.locked.run run --label final --split all --stage all --env-file .env
```

Commit e7574ac.

## Open

- Misread cells: DAR-663 (two models must agree on a number before it is shown).
