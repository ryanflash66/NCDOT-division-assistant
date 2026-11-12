# DAR-669. The concrete table question (TMP Design Manual p.38) against its asphalt twin (p.37)

Checked on `origin/main` at 5d6f713 on Nov 11, Work Zone Traffic Control division, asker Utilities, local app
(`hosted/`, committed index, OpenRouter free models, OpenAI off). The Nov 5 failure no longer reproduces: both
twin questions return the right value on the right page on every run.

The two questions (offset 14 ft, design speed 40 mph):

- asphalt: "what is the maximum deflection for the NC-PCB impact design table on asphalt pavement at an offset of 14 ft and a design speed of 40 mph?" Expected 27.42 in, PDF p.37 (printed Page 13, Figure 4).
- concrete: the same with "concrete pavement". Expected 19.42 in, PDF p.38 (printed Page 14, Figure 5).

## 1. Is p.38 in the top 5 for the concrete question?

Yes. Retrieval only (`Runtime.retrieval` from `evaluation/locked/run.py`, the app's own retriever settings, no model call):

| question | top 5 pages (reranker score) |
|---|---|
| asphalt | p.37 x5 (6.72) |
| concrete | p.38 x5 (6.96) |
| concrete, exact figure name | p.38 x5 (7.20) |

All five slots hold chunks of the right page, and the twin's page does not appear at all: p.37 is rank 1 for the asphalt question
(p.38 absent), p.38 is rank 1 for the concrete question (p.37 absent). The captioned `context` line on each chunk
("Figure 4 ..." on p.37, "Figure 5 ..." on p.38) and the caption/table-number keyword field are what separate the two pages. In the index, 19.42 sits
on p.38 only; 27.42 is on p.37 and also in another cell of the p.38 table, so the concrete case's check of "27.42 absent from the answer" is a real
test of which row the model read, not of which page it saw.

## 2. Does the number guardrail or the refusal rule block the answer when a shown passage says "asphalt"?

Not on current main. For the concrete question the passages the model sees are all p.38 chunks (answer above), and none of them contains the word
"asphalt" (the only chunks with "asphalt" are p.37's, not retrieved). 19.42 is in a p.38 chunk, so the number check (`unverified_numbers`,
`hosted/divrag/numbers.py`) has nothing to flag. No refusal occurred in 12 model calls, so the refusal rule was not exercised. I did not reproduce
the Nov 5 refusal, so what blocked it that day is not established from this run. Two commits from Nov 5 changed table-page retrieval (6cff798 "Score a caption and
table-number field in the keyword search so a question naming a table finds its captioned page", and 5c2562e, the index rebuild); whether either came
after the failing run I did not check, so that is a possible explanation, not a measured one.

## 3. Does the refusal also happen with the exact figure name?

No. "Figure 5 NC-PCB impact design table for CONCRETE pavement: what is the maximum deflection at an offset of 14 ft and a design speed of 40 mph?"
returned 19.42 inches on p.38 (printed 14) on 3 of 3 runs, no refusal.

## 4. Does the "ask other divisions instead" hint appear, and why?

Not in any of the 12 runs (no `refused`, so no suggestion step). On a refusal the hint comes from `Answerer.suggest_divisions`: it reranks the question
in each other division and suggests those whose best reranker score is at least `SUGGEST_THRESHOLD`, which is **0.0**. A cross-encoder score of 0 is a
low bar, so a refusal about a table question can show the hint even when the other division has nothing that answers it. That explains the hint on
the Nov 5 refusal; it is separate from why the model refused. Not changed here (the refusal path belongs to DAR-662).

## 5. Three runs of each question through the local app

| # | question | answer value | cited PDF page | printed page | model | refused | seconds |
|---|---|---|---|---|---|---|---|
| 1 | asphalt | 27.42 inches | 37 | 13 | nemotron-3-ultra-550b-a55b:free | no | 3.2 |
| 2 | asphalt | 27.42 inches | 37 | 13 | nemotron-3-ultra-550b-a55b:free | no | 1.6 |
| 3 | asphalt | 27.42 inches | 37 | 13 | nemotron-3-ultra-550b-a55b:free | no | 2.0 |
| 1 | concrete | 19.42 inches | 38 | 14 | nemotron-3-ultra-550b-a55b:free | no | 3.0 |
| 2 | concrete | 19.42 inches | 38 | 14 | nemotron-3-ultra-550b-a55b:free | no | 2.1 |
| 3 | concrete | 19.42 inches | 38 | 14 | nemotron-3-ultra-550b-a55b:free | no | 8.5 |
| 1 | concrete, figure name | 19.42 inches | 38 | 14 | nemotron-3-ultra-550b-a55b:free | no | 4.0 |
| 2 | concrete, figure name | 19.42 inches | 38 | 14 | nemotron-3-ultra-550b-a55b:free | no | 3.6 |
| 3 | concrete, figure name | 19.42 inches | 38 | 14 | nemotron-3-ultra-550b-a55b:free | no | 2.8 |

Asphalt 3/3 and concrete 3/3 (right value, right PDF page, no refusal); the figure-name variant 3/3. Then one run of the new regression check
(below) added 3 more calls, all passing (7.2, 6.8 and 6.0 s). The fallback model was never needed. 12 model calls in total.
Three runs per question show no failure; they cannot rule out a rare one (3/3 has a 95% Wilson interval of 44% to 100%).

## What was added

- `eval/twin_table_questions.json`: the pair (asphalt, concrete) plus the figure-name variant. Each case has `must_contain` (its own value), `must_not_contain`
  (the twin's value, 27.42 vs 19.42), `pages` and `printed_pages`, and `twin_pages`. It is kept apart from `eval/image_table_questions.json` so that file's
  15-question figures (quoted in `docs/` and several tools) keep their meaning. Not in `evaluation/locked/` or `evaluation/heldout/`.
- `prototype/image_table_check.py`: `--cases` for `search` and `answers`; `grade_answer()` grades value, twin value, refusal, cited PDF page and printed page; `answers`
  prints the problems per case and exits 1 when a graded case fails; `search` records the twin page's rank and exits 1 when the case's own page is
  outside the top 5 or the twin's page outranks it.
- `tests/test_image_table_check.py`: model-free tests of the case file, of `grade_answer` (swapped value, wrong page, refusal, wrong printed page) and, against the
  committed index, that 19.42 is on p.38 only and each page's table chunks carry their own figure caption. Retrieval ranks need the ONNX models, so they stay in
  the `search` command, not in the unit tests.
- What was missing before: `eval/image_table_questions.json` already had a pair (concrete 20 ft/60 mph, asphalt 44 ft/70 mph), but its `answers` run recorded only the cited page; a wrong value or a
  swapped table with the right page, or a refusal flagged only as "refused", would not fail anything. The two cases now also carry `must_contain` (25.37, 44.53), and `answers` grades any case that has value fields, so they are graded when that file is run.

## Not done

No change to `hosted/divrag/`. If the concrete question fails again, the data to collect is the ranks (as above), the passages in the prompt and which rule
refused; the refusal retry and the 0.0 suggestion threshold are DAR-662's area.
