# DAR-661 and DAR-718: the held-out test set and its first result

**What this is.** A new test set of 311 questions, written without looking at how the assistant answers, and the assistant's score on it. It replaces the locked set as the measure, because the locked set's misses were read to design fixes (decision log D17).

**Result in one line.** On 286 locked questions, one run, free models: value right 201/242 (78–87%), cited PDF page right 207/237 (83–91%), confident wrong answers 31/286 (8–15%). The targets are value right 99.9% and cited page right 95%; neither is met.

## How to read the numbers

- Every number is count/n with its 95% Wilson interval. One run; a rerun on free models will differ by a few questions.
- **Value right:** the expected value is in the answer. Refused answers count as wrong.
- **Cited page right:** every page the answer cites is a gold page. Counted over answers that were not refused.
- **Confident wrong:** a cited answer with the wrong value, a cited answer to a must-refuse question, or a cited answer that picks one case when the question left the deciding variable out.
- These questions are harder on purpose than the old set: 12 edge cases that had no or few questions before now have 9 to 26 locked questions each. The two sets' totals are not the same measurement, so the old and new columns below are not a before and after.

## Result (locked split, 286 questions, 221 distinct gold pages)

| measure | held-out set, Nov 11 | old locked set, final run (for orientation only) |
|---|---|---|
| value right | 201/242 (78–87%) | 221/245 (86–93%), both splits |
| cited PDF page right | 207/237 (83–91%) | 147/229 (58–70%), both splits |
| cited printed page right | 150/208 (66–78%) | |
| value and cited page both right | 180/242 (69–79%) | |
| confident wrong | 31/286 (8–15%) | 8/232 (2–7%) |
| answerable question refused | 19/256 (5–11%) | 14/204 (4–11%) |
| must-refuse question answered | 4/30 (5–30%) | |
| question missing a variable: asked or showed every case | 9/14 (39–84%) | |
| right page ranked first / in the top 5 | 171/256 (61–72%) / 228/256 (85–92%) | |
| answers with no citation | 0/286 | 72 of the 82 citation misses were uncited |
| answer time | median 2.4 s, p90 4.1 s, max 15.8 s | |

- **Run:** commit 34eb374, index sha 477f07b420b4 (13,240 chunks), `TOP_K` 5, models nemotron-3-ultra (254 answers) and nemotron-3.5-super-vl (32). Report: [`../heldout-set/baseline.md`](../heldout-set/baseline.md) and `.json`. Run log: [`../heldout-set/RUNS.md`](../heldout-set/RUNS.md), one line.
- **The citation fix (PR #42) holds on clean questions:** no answer came back without a citation, and the cited PDF page is right for 207 of 237.
- **Where the 31 confident wrong answers are:** 25 on ordinary answer questions (6 of them lists cut short at a page break), 4 on must-refuse questions, 2 on questions missing a variable.
- **By division, value right:** Traffic Management and Signal Design 67/85 (69–86%), Utilities 67/83 (71–88%), Work Zone Traffic Control 67/74 (82–95%).
- **Not scored: the OpenAI path** (DAR-679). The key is only in Vercel; the runner now answers the way the site does when `LLM_PROVIDER=openai` and the key are present locally.

### Weakest rows (locked questions)

| edge case | result |
|---|---|
| appendix page numbers | value right 5/10 (24–76%) |
| rotated or landscape page | value right 7/13 (29–77%) |
| answer needs two pages | value right 8/15 (30–75%) |
| list that runs over a page break | every item given 8/14 (33–79%) |
| question missing a variable | asked or showed every case 9/14 (39–84%) |
| false premise | gave the documents' value 10/15 (42–85%) |
| in scope but not in the documents | refused 9/12 (47–91%) |

The full matrix is in [`../redo-methods.md`](../redo-methods.md) section 7.

## How the set was made

- **Three authors, one per division,** each an AI assistant session working only from the PDF pages. They could not open the old question files, any run report, the methods document or the index, and ran no retrieval or model. Notes per division: [`../heldout-set/authoring-wztc.md`](../heldout-set/authoring-wztc.md), [`-utilities.md`](../heldout-set/authoring-utilities.md), [`-tmsd.md`](../heldout-set/authoring-tmsd.md).
- **Fresh pages.** No gold page is one of the 292 pages the locked set or the development sets use. At most 2 questions per page.
- **311 questions:** Work Zone 100, Utilities 105, Traffic Management 106. 243 answer, 38 must-refuse, 15 false-premise (the right reply gives the documents' value), 15 missing a variable.
- **Checked against the page:** 266 gold values found by script in the page's text, 13 in its OCR text, 32 read off the rendered page (scans, rotated pages, drawings) with no machine check.
- **Split by the same hash rule** as the locked set: 286 locked, 25 tuning. **Frozen before scoring:** `evaluation/heldout/HELDOUT.sha256` (`8c254f56…5a45`) in commit 34eb374; the run came after.
- **Scored by the same rules** as the locked set, plus: a list needs every item; a question missing a variable is right when the answer shows every case or asks; a reply that a section is "reserved" counts as declining; citation markers are not read as values.

## Edge cases (DAR-718)

- All 12 cases DAR-718 named now have 8 or more locked questions: degraded scans 11, ranges 26, conditional rules 19, superseded editions 9, multi-column 24, symbols 17, not in the documents 12, duplicate sections 15, contents-page decoys 15, lists over a page break 14, missing variable 14, revision marks 14. False premise has 15.
- 31 of 32 rows are covered. Out of scope has 7 locked questions, one short.
- **Rare in the documents, with the checks in the authoring notes:**
  - Superseded editions: 5 real old/new pairs in Work Zone, 2 in Utilities, 2 in Traffic Management. The 2024 CFR parts match their older reprints.
  - Degraded scans: none in Work Zone (all 42 image-only pages are clean exports).
  - Revision marks: only "[Reserved]" and placeholder pages; no strikethrough, revision bars or watermarks were found.
- The old locked files keep their tag spellings: changing them would break their frozen hash. The new set uses one fixed tag per row (`evaluation.heldout.EDGE_CASES`), and the matrix is generated by `python -m evaluation.heldout.matrix`.

## Limits

- **No person reviewed the questions.** A wrong gold value would show up as a wrong answer. The locked items have not been read one by one after the run, so that was not checked.
- **The tuning split is small:** 25 questions, where the hash rule would give about 60. The authors picked pages that hash to the locked side for the priority cases. The rule was not bent, but fixes have little to tune on here.
- **Authors and answering models are different models,** but all are language models; questions a person would ask may differ.
- **Short gold values match loosely** ("three", "prohibited"), so a few value-right counts may be generous.
- **One run.** Free-model answers vary between runs.

## Reproduce

```bash
.venv\Scripts\python -m evaluation.heldout.run check
.venv\Scripts\python -m evaluation.heldout.run run --label NAME --split locked --env-file .env
.venv\Scripts\python -m evaluation.heldout.matrix --report docs/heldout-set/NAME.json
```

Each run of the locked split adds a line to `docs/heldout-set/RUNS.md`. Read a run's tables, not its items: an item inspected in detail has to be replaced.
