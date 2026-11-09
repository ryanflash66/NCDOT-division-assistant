# Locked test set (DAR-653)

The locked test set measures whether the hosted demo answers table, figure and
scan questions with the right value from the right page, and refuses what the
documents don't cover. It is scored by rule (page, value, unit, abstention),
with every result as count/n plus a 95% Wilson interval, and it is **run at
release only**. Everything else (the 15 image/table questions in
`eval/image_table_questions.json`, the 83 known-page questions behind
`eval/retrieval_pages.json` and `eval/table_questions.json`, the 90 RAGAS
questions in `evaluation/testset.json`) is a development set, permanently:
each has been looked at while fixing the pipeline, so none of them can say
how the pipeline does on questions nobody tuned for.

Files:

| file | what |
|---|---|
| `wztc.json`, `utilities.json`, `tmsd.json` | the question files, one per division (authored separately under DAR-653; the runner works with none) |
| `LOCKED.sha256` | the hash of the locked items (`freeze`); `check` fails when they change |
| `normalize.py` | number and unit normalization (the hosted number guardrail copies these rules) |
| `score.py` | per-item scores, Wilson intervals, aggregates per stratum, the abstention table |
| `validate.py` | schema checks for the question files |
| `run.py` | the runner: `run`, `freeze`, `check`, `validate` |
| `results/cache.jsonl` | answers cached per item, model list and index (gitignored) |
| `docs/locked-set/<label>.{json,md}` | each run's report; `docs/locked-set/RUNS.md` counts the locked runs |

## Running

From the repo root, with the full `requirements.txt` and `hosted/requirements.txt` installed:

```bash
# the schema checks (also run by `run` before anything else)
.venv\Scripts\python -m evaluation.locked.validate

# retrieval only (no model calls): right document and page in the top 5
.venv\Scripts\python -m evaluation.locked.run run --label tune-01 --split tuning --stage retrieval

# answers too: the hosted Answerer in-process, one free-model call per item (two on a retry)
.venv\Scripts\python -m evaluation.locked.run run --label tune-01 --split tuning --env-file .env

# a release run on the locked split (counted in docs/locked-set/RUNS.md)
.venv\Scripts\python -m evaluation.locked.run run --label v1.3 --split locked --env-file .env

# freeze the locked items, and check them (CI: exit 1 when they differ)
.venv\Scripts\python -m evaluation.locked.run freeze
.venv\Scripts\python -m evaluation.locked.run check
```

`run` is the default subcommand, so `python -m evaluation.locked.run --label NAME ...` is the same as `... run --label NAME ...`.

Options of `run`: `--split tuning|locked|all` (default `tuning`, so the
locked split is only ever run on purpose), `--stage retrieval|answer|all`,
`--index DIR` (default `INDEX_DIR` or `hosted/index`), `--only ID ...`,
`--limit N`, `--max-requests N` (cap on new model calls, the free models share
one daily quota), `--env-file PATH` (default: the repo's `.env`, found above a
git worktree too; it is never copied), `--questions DIR` (default this
directory), `--out DIR`, `--cache PATH`, `--pause SECONDS`, `--tag NAME`.

The answer stage runs exactly what `/api/ask` runs (`hosted/index.py
_answer`): the same index, retriever, prompt, citation check, retry, refusal
and request budget, from the same settings (`divrag.config`). Answers are
cached in `results/cache.jsonl` keyed by item id, the model list and the
index's fingerprint (plus `#k<N>` when `TOP_K` isn't 5 and `#<tag>` with `--tag`, so a run of changed answering code asks again instead of scoring cached answers), and tied to the question's wording; a run stopped by the
free models' daily cap (`DAILY_LIMIT`) writes the report for what it has and
the next run continues from there. Per-minute limits are waited out.

The report (`docs/locked-set/<label>.json`) holds every item's scores, the
aggregates and the run's metadata (commit, index path, size and fingerprint,
settings, timestamp); `<label>.md` is the same as tables. Two runs on the same
items can be compared item by item from the JSON (paired, which is what the
research note recommends: `.handoff/redo-nov4/C-eval-edgecases.md`, section 3.1).

## Schema

One file per division, `{"division": "<id>", "items": [...]}`:

```json
{"id": "wztc-001", "division": "wztc", "asker": "utilities",
 "question": "What is the maximum deflection for an offset of 14 ft at 40 mph?",
 "type": "table",
 "edge_cases": ["merged_header", "landscape"],
 "expected": {"source": "TMP Design Manual (Combined, No Links).pdf", "pdf_pages": [37],
              "printed_pages": ["13"], "value": "27.42", "accept": ["27.42"], "unit": "ft"},
 "refuse": false,
 "split": "locked",
 "verified_by": "page_text_match",
 "note": ""}
```

- `division`: the division asked (the target); `asker`: the asker's division (it only changes the prompt's wording). Both are ids from `hosted/divrag/divisions.py`.
- `type`: one of `table`, `figure`, `scan`, `rotated`, `multipage_table`, `text`, `unanswerable`, `table_id`, `page_ref`, `units`, `footnote`, `duplicate_pages`, `cross_ref`.
- `edge_cases`: free tags; each becomes a stratum of the report.
- `expected.source`: the document's `file` in `divisions.py` for that division; `pdf_pages`: 1-based PDF page indexes (the first one is the split key); `printed_pages`: the page labels printed on those pages, as strings, `""` when a page has none; `value`: the gold answer; `accept`: other wordings that count (`"27.42 ft"`, `"two inches"`); `unit`: for the record.
- Unanswerable: `"expected": null, "refuse": true`.
- `split`: `tuning` or `locked`, by the rule below; the validator checks it.
- `verified_by`, `note`: how the gold was checked (page text, page image, a person), and anything a reader needs.

## The split rule

Split by **gold page**, not by question, so a page tuned on is never also a
locked page (questions about the same page or table are one observation, not
several):

```python
digit = int(hashlib.sha1(f"{source}|{pdf_pages[0]}".encode()).hexdigest()[-1], 16)
split = "tuning" if digit < 3 else "locked"       # about one item in five is tuning
```

Unanswerable items have no page and hash on their `question` the same way.
`validate` fails on an item whose `split` disagrees with the rule.

## Scores

Per item (`score.py`): `right_document`, `page_rank` (1-based rank of the
first gold page in the top 5, or null), `hit1`, `hit5`, `cited_pages_pdf`,
`cited_pages_printed`, `cited_page_ok_pdf` (every cited page is a gold page of
the gold document; a cited range counts when it overlaps), `cited_page_ok_printed`
(the same against `printed_pages`, when the API sends `Source.printed_page`;
null otherwise), `value_ok` (`normalize.value_matches`), `strict_ok`
(`value_ok and cited_page_ok_pdf and not refused`: the right answer from the
right page), `refused`, `uncited`, `unverified` (the hosted guardrail's list,
when present), `critical` (a confident wrong answer: cited, not refused, wrong
value; or a cited answer to an unanswerable question), `seconds`, `model`.

Aggregates: for all items and per split, division, type, edge case and
asker-vs-target, each metric as count/n with its Wilson interval, the number
of distinct gold pages (clusters) in the stratum, and the 4-way abstention
table (answerable × refused) with the over-refusal and false-answer rates.
When the critical count is 0, the report adds the one-sided 95% upper bound
on the rate (0 of 50 only shows it is under 5.8%).

Values are compared after normalization (`normalize.py`): thousands commas
dropped, fractions to decimals (`1-1/2` → `1.5`), `12'`/`12-foot`/`12 feet`/
`12 ft.` → `12 ft`, inches → `in`, `mi/h` → `mph`, `percent` → `%`, `°` → `deg`,
trailing `.0` dropped; numbers within 1e-9 once the unit agrees, anything else
as a case-insensitive, whitespace-collapsed substring.

## How not to tune on the locked set

- Tune on the `tuning` split (and the dev sets) only. `run` defaults to it.
- Run the locked split at a release gate only, and let `run` record it in
  `docs/locked-set/RUNS.md`: that count is part of any result quoted from it.
- Read the locked run's tables, not its items. If a locked failure is
  inspected in detail (the question, the page, the answer), that item is now a
  development item: replace it with a fresh one on another page and re-`freeze`.
- Never add, drop or edit a locked item to make a run pass; `check` exists so
  a change is noticed, and CI should run it.
- Questions should be written from the PDF page, not from the system's output,
  by someone who did not build the pipeline where possible, and verified
  against the page (`verified_by`).

Reading the numbers: at 15 items a 14/15 result is 70–99%; at 50, 45/50 is
80–95%. A stratum with few clusters is one or two observations, whatever its
item count. Compare two pipeline versions item by item on the same questions
(a paired test), not by their averages.

## The judge (not implemented here)

Page, value, unit and abstention need no judge. A free LLM judge, if one is
added for the prose parts (faithfulness, completeness), must be calibrated
first, per the research note (section 5): hand-grade 30 answers to start,
pass/fail with a one-line reason, and keep grading until no new failure mode
appears (about 100 per failure mode); measure the judge's true-positive and
true-negative rate on "bad answer" separately, require each at least 0.85
(and kappa at least 0.6) before its verdicts count, re-grade a random 10% of
each release by hand, re-calibrate whenever the judge model or rubric
changes, and never let the answering model judge its own answers. Any paid
judge API needs Dr. Namian's approval.
