# PR #42: answers that cite nothing

**What changed** (decision log D14, D15). An answer with no `[n]` is asked once more, by the model that wrote it, to cite its passage. The new reply is kept only if it cites a passage and keeps every number of the first answer. If the answer is still uncited, it is cited to the one passage holding all its numbers, only when exactly one passage does. The answer payload says which happened (`citation_fix`).

**Merged:** PR #42 (3c1b0c7), documented in PR #43 (b05ea5f).

## Why: where the citation misses were (locked split, after PR #41)

| | count |
|---|---|
| citation misses that cited nothing | 61/70 (77–93%) |
| cited answers with the right page | 120/129 (87–96%) |
| same over both splits | 72/82 (79–93%) and 147/157 (89–97%) |

## Options replayed on the cached answers (both splits, 72 uncited answers)

| option | right page | wrong page | left uncited |
|---|---|---|---|
| cite the best-ranked passage holding the numbers | 43/72 (48–70%) | 19/72 (18–38%) | 10 |
| the same, only when exactly one passage holds them | 33/72 (35–57%) | 1/72 (0–7%) | 38 |
| ask the model again, then the second option (shipped) | measured on the tuning split below | | |

Of the answers the second option cites, 33/34 (85–99%) get the right page; the first option gives a wrong page 19 times in the 62 it cites.

## Before and after on the tuning split

The locked split was not rerun: its misses were read to design this fix (D17). From `docs/locked-set/tuning-final2.md` and `tuning-cite2.md`:

| | before | after |
|---|---|---|
| cited PDF page right | 27/39 (54–81%) | 37/39 (83–99%) |
| cited printed page right | 21/35 (44–74%) | 28/35 (64–90%) |
| value right | 39/41 (84–99%) | 39/41 (84–99%) |
| value and cited page right | 27/41 (51–78%) | 37/41 (77–96%) |
| wrong value shown with a citation | 0/48 (0–7%) | 0/48 (0–7%) |
| answerable question refused | 2/41 (1–16%) | 2/41 (1–16%) |

**8 passages instead of 5** (`tuning-cite2-k8.md`): value right 40/41 (87–100%), refusals 0/41 (0–9%), but one confident wrong answer, 1/48 (0–11%), from a wrong-row read. Not adopted (DAR-664).

**Raw results:** `docs/locked-set/tuning-final2.{json,md}`, `tuning-cite2.{json,md}`, `tuning-cite2-k8.{json,md}`.

## Reproduce

```bash
.venv\Scripts\python -m evaluation.locked.run run --label tuning-cite2 --split tuning --stage all --tag cite2 --env-file .env
set TOP_K=8
.venv\Scripts\python -m evaluation.locked.run run --label tuning-cite2-k8 --split tuning --stage all --tag cite2 --env-file .env
```

Commit 3d0adb9. `--tag` keeps the run from scoring answers cached before the change.

## Open

- An honest after-number on unseen questions: DAR-661.
- Asked again, the model sometimes re-read a table and changed a right value (Detail 3-2A: 5 ft → 6 ft, 330 ft → 290 ft); the number rule rejects those replies, but they stay uncited.
