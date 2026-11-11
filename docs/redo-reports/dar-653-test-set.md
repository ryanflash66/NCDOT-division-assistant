# DAR-653: locked test set and scorer

**What changed.** A 280-question test set with known answers and pages, a rule-based scorer with Wilson intervals, and a runner that answers in-process exactly as `/api/ask` does (decision log D1).

**Merged from:** `ryanflash166/dar-653-locked-set-scorer` (dec7908), `-locked-questions-wztc` (41c0c76), `-locked-questions-utilities` (0459d18), `-locked-questions-tmsd` (82ffa7c); main via PR #41 (7489cdf).

## The set

| | Work Zone Traffic Control | Utilities | Traffic Management and Signal Design | all |
|---|---|---|---|---|
| answerable | 90 | 70 | 85 | 245 |
| must be refused | 10 | 10 | 15 | 35 |
| tuning / locked | 20 / 80 | 12 / 68 | 16 / 84 | 48 / 232 |

- 195 distinct gold pages. Question types: text 63, table 58, scan 19, figure 17, rotated 16, footnote 14, table over a page break 13, units 12, printed page named 10, cross-reference 9, table number named 8, duplicate pages 6, must be refused 35.
- Split by hash of document and first gold page (refusals hash the question); nothing moved by hand. Frozen in `evaluation/locked/LOCKED.sha256`.
- Each value was checked by script against the page's text layer or its OCR text. No domain expert reviewed the questions.
- How each division's questions were written: `docs/locked-set/authoring-wztc.md`, `authoring-utilities.md`, `authoring-tmsd.md`.

## Before and after on the locked split

This ticket is the measuring stick, so its "result" is the baseline it made possible. Locked split, 232 questions:

| | before the redo | after PR #41 |
|---|---|---|
| value right | 179/204 (83–92%) | 183/204 (85–93%) |
| cited PDF page right | 94/185 (44–58%) | 120/190 (56–70%) |
| value and cited page right | 93/204 (39–52%) | 117/204 (50–64%) |
| wrong value shown with a citation | 6/232 (1–6%) | 8/232 (2–7%) |
| answerable question refused | 19/204 (6–14%) | 14/204 (4–11%) |
| unanswerable question answered | 4/28 (6–31%) | 4/28 (6–31%) |

**Raw results:** `docs/locked-set/baseline-pre-answers.{json,md}`, `docs/locked-set/final.{json,md}`.

## Reproduce

```bash
.venv\Scripts\python -m evaluation.locked.validate
.venv\Scripts\python -m evaluation.locked.run check
.venv\Scripts\python -m evaluation.locked.run run --label final --split all --stage all --env-file .env
```

Commit e7574ac for both answer runs. The "before" run points `--index` at the pre-redo index (main at 8feefe6, rebuilt, 10,746 chunks, sha 9139d26da892), with the keyword field off and every chunk reranked. Both "before" runs record uncommitted changes in the working tree (`baseline-pre.md`, `baseline-pre-answers.md`); the `final` run was made from a clean tree.

## Open

- The scorer fails an answer that also cites a correct second page (10 misses to hand-check).
- Edge-case labels differ between the division files (`rotated` / `rotated_text`, `cross_ref` / `cross_reference`).
- The locked split was read for causes after the final run, so it is no longer clean (D17, DAR-661).
