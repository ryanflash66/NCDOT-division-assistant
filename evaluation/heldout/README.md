# Held-out test set (DAR-661, DAR-718)

The locked set (`evaluation/locked/`) was read to find the causes of its
misses, so a fix designed from them looks better on it than it is (decision
log D17). This set is the clean replacement: new questions on pages no older
test set uses, written without looking at the locked misses or at any system
output, frozen in git before the first scored run.

It uses the locked set's schema, split rule, scorer and runner
(`evaluation/locked/README.md`). What is different:

| | |
|---|---|
| question files | `wztc.json`, `utilities.json`, `tmsd.json` here; ids are `<division>-hNNN` |
| hash | `HELDOUT.sha256` (`freeze`, `check`) |
| reports | `docs/heldout-set/<label>.{json,md}`; every run that includes the locked split is counted in `docs/heldout-set/RUNS.md` |
| answer cache | `results/cache.jsonl` (gitignored) |
| gold pages | none of the pages in the locked set or the development sets (`eval/*.json`, `evaluation/testset.json`) |
| edge-case tags | only the tags in `evaluation.heldout.EDGE_CASES`, one per row of the edge-case matrix; every command fails on any other tag |
| how it was written | `docs/heldout-set/authoring-<division>.md`; the DAR-737 replacements in `authoring-dar-737.md` |
| retired items | `retired/`: items read in detail, so development items now; not loaded by any command, and their gold pages stay out of new items |

## Running

```bash
.venv\Scripts\python -m evaluation.heldout.run validate
.venv\Scripts\python -m evaluation.heldout.run check
.venv\Scripts\python -m evaluation.heldout.run run --label NAME --split locked --env-file .env
.venv\Scripts\python -m evaluation.heldout.matrix --report docs/heldout-set/NAME.json
```

The options are the locked runner's. With `LLM_PROVIDER=openai` and
`OPENAI_API_KEY` in the environment the run answers as the site does (OpenAI
first, the free models behind it) and its calls count against the month's
OpenAI limit (DAR-715); otherwise the free OpenRouter models answer.

The OpenAI key is a hidden secret in the Vercel project and not in any local
`.env`, so the OpenAI path is scored through the deployed site:

```bash
.venv\Scripts\python -m evaluation.heldout.run run --label NAME --split locked --pause 8 --site https://ncdot-division-assistant-iota.vercel.app
```

`--site` posts each question to the site's `/api/ask` and scores the reply;
the site's own settings (from `/api/health`, saved in the report) answer, and
only the retrieval columns (hit@k, right document) come from the local index.
It scores whatever the site has deployed, so it measures main as shipped, not a
branch. The site allows 8 questions a minute per IP; `--pause 8` keeps under it
and a 429 is waited out.

## Schema additions

- `behaviour` (every item here has it): what the right reply does.
  - `answer`: state the gold value from the gold page.
  - `refuse`: the documents don't cover it (`refuse: true`, `expected: null`).
  - `correct`: the question asserts something false; `expected` holds the documents' value and page, and the item is scored as an answer.
  - `clarify`: the question leaves out a variable the answer depends on; `expected.all_of` lists the value of each branch.
- `expected.all_of`: parts the answer must all contain, each a wording or a list of wordings. Used for lists that run over a page break and for the branches of a `clarify` item.

## Scores added for these

- With `all_of`, `value_ok` needs every part in the answer.
- `clarify_ok` (clarify items only): the answer shows every branch, or names none and asks for the variable. Clarify items have no `value_ok` or `strict_ok`, so they stay out of the value rate. A cited answer that gives some branches and not the others counts as `critical`: it picked a default without saying so.

## Rules

The locked set's rules hold (`evaluation/locked/README.md`, "How not to tune
on the locked set"): tune on the tuning split only, run the locked split at a
release gate, read a locked run's tables and not its items, never edit an
item to make a run pass. A locked item whose failure is inspected in detail
is a development item from then on: replace it with a fresh one on another
page and re-freeze.
