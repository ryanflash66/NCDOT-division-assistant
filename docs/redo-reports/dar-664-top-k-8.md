# DAR-664. Show 8 passages instead of 5, with a wrong-row guard

## What was asked

The right page is in the top 8 for 231 of 245 answerable locked questions, but the model sees only the top 5 (`TOP_K`, default 5). On the tuning split, 8 passages gave 0 refusals instead of 2, but one answer read the wrong row of Detail 3-2A, so `TOP_K` stayed at 5 (decision D15). This ticket builds a guard against wrong-row reads that works on its own, and measures 5 against 8 passages with the guard off and on.

`TOP_K` was not changed. The default changes only if the held-out result is better and wrong answers do not rise; that run belongs to the coordinator.

## What was built

`hosted/divrag/rowcheck.py`, behind the setting `ROW_GUARD` (`off` by default; `on` / `1` / `true` turn it on). When an answer cites a passage with a table and states a number, it:

1. reads the table rows of the cited passages: Markdown pipe rows, and the labelled rows after a `Rows:` line (`Offset (ft)=14 | Maximum Deflection | Design Speed(mph): 30=25.16, 40=27.42`);
2. finds the rows whose data cells hold the answer's number (numbers normalized as in `numbers.py`; a number the question itself gave is skipped);
3. counts, for each row, how many of the question's label terms its label cells carry: the question's numbers (the offset 14), and, in labelled rows only, its words ("maximum", "deflection");
4. flags the number when another row of the same table carries more of those labels than every row holding the number.

The flag goes into `Answer.unverified`, the existing mechanism, so the page shows it as an unverified number. The check runs after the number recheck and never asks the model again.

It stays quiet when it cannot tell: no table row in the cited passages, the number in no row's data cells, an answer that cites nothing, a reference such as "Detail 3-2A" or "Table 4-1" (not read as a label), header rows (rows above the `---` line), or a table it cannot split into label and data cells. Tests are in `tests/test_hosted_rowcheck.py` (fake retriever and LLM).

## The four runs

Tuning split, 48 items (41 answerable, 7 unanswerable). Same code, same index, free models, `--tag dar664`; each cell is count/n with its 95% Wilson interval.

| | k=5, guard off | k=5, guard on | k=8, guard off | k=8, guard on |
|---|---|---|---|---|
| refusals on answerable items | 2/41 (1-16%) | 2/41 (1-16%) | 0/41 (0-9%) | 0/41 (0-9%) |
| value right | 39/41 (84-99%) | 39/41 (84-99%) | 40/41 (87-100%) | 40/41 (87-100%) |
| value right and cited page right | 38/41 (81-97%) | 38/41 (81-97%) | 36/41 (74-95%) | 36/41 (74-95%) |
| critical (confident wrong) | 0/48 (0-7%) | 0/48 (0-7%) | 1/48 (0-11%) | 1/48 (0-11%) |
| flagged | 0/39 (0-9%) | 0/39 (0-9%) | 0/41 (0-9%) | 0/41 (0-9%) |
| false flag | 0/39 (0-9%) | 0/39 (0-9%) | 0/40 (0-9%) | 0/40 (0-9%) |
| answer time, median / p90 | 6.1 s / 14.9 s | same | 9.3 s / 21.1 s | same |

The guard columns were computed offline, on the same answers as the guard-off columns: the 96 answers asked once (k=5 and k=8, guard off) were saved with their passages in the run cache, and `misread_numbers` was applied to each cited answer and its cited passages. The model-call budget (120) did not allow four live runs. A live run with `ROW_GUARD=on` would differ only where the guard flags, and it flags nothing here.

Runs: `docs/locked-set/dar-664-k5.{md,json}`, `docs/locked-set/dar-664-k8.{md,json}`. Three k=5 questions and a few retries hit 504 timeouts from the free models and were asked again; each report covers all 48 items.

Answer times are not a clean comparison: the k=8 run ran while other workers were sharing the free models' quota, and the first questions of that run took 12 to 20 s each. The longer prompt adds time on its own, but how much cannot be separated here.

### Prompt size

The passages block of the user message, median over the 48 tuning items (characters; tokens estimated as characters / 4):

| | median | p90 | tokens (estimate) |
|---|---|---|---|
| 5 passages | 9,092 chars | 13,124 | about 2,300 |
| 8 passages | 13,338 chars | 19,620 | about 3,300 |

8 passages add 47% to the block. The cached passages lack the context line that `answer.passage_text` puts before a page's captions, so the real block is a little larger in both columns.

## Findings

- **Refusals:** 8 passages removed both refusals (wztc-034, wztc-037), as in D15. Both are now answered with the right value, but wztc-037 cites a page that is not the gold one.
- **Cited page:** value-and-page-right fell from 38/41 to 36/41. In three items the 8-passage answer cites a second source beside the right one ([1][2]), or a different page: tmsd-034, wztc-037, wztc-041. The values stayed right. This is inside the intervals but points the same way as the longer prompt.
- **Detail 3-2A (tmsd-003) read the wrong row again at k=8.** At k=5 it answered 330 ft (right). At k=8 it answered "290 ft for a design speed of 50 mph with ADT 600-2000. The passages do not provide a value for 60 mph", a confident wrong answer (1/48). The same happened in the first k=8 run behind D15. The app run with `TOP_K=8 ROW_GUARD=1` gave the same wrong answer.
- **The guard does not flag it.** The cited page (10) is a scanned drawing; its text is OCR output in which the table's rows are jumbled ("50 22 320 20 290 16 260 12 240 ..."), so there are no table rows to read and the check stays quiet by design. The answer does repeat conditions that differ from the question's (50 mph and ADT 600-2000 against 60 mph and 800-2000); a check on restated conditions could catch this one, but it would also flag legitimate answers that mention other speeds, so it was not built.
- **Where the guard can act at all is narrow.** Of 39 cited answers at k=5 and 41 at k=8, 11 and 12 cite a passage with a parsable table row, and the answer's number sits in a table row for 4 of them. On those 4 the guard flagged nothing, and the answers were right, so it raised no false flag. It flags the intended case in unit tests (the TMP deflection table: 25.86 in for an offset of 14 ft is the offset-8 row's value; 12.1 degrees for "maximum deflection" is the impact-angle row's value), but this split has no wrong-row read in a parsable table to show it on.

## Answer to the ticket's questions

- Does the Detail 3-2A wrong-row read happen again at k=8? Yes, in this run and in the earlier one.
- Does the guard flag it? No: the cited passage is an OCR'd drawing, not table rows.
- Is it safe to raise `TOP_K`? Not on this evidence. 8 passages remove the refusals but still produce the one confident wrong answer, with nothing to catch it, cost 3 cited-page matches, and add about 47% to the prompt and several seconds to the median answer.

## Not done

- No live run with `ROW_GUARD=on`; the guard columns are offline on the same answers.
- No test on a wrong-row read inside a parsable table: none occurred on the tuning split. Two table questions were asked through the app with `TOP_K=8 ROW_GUARD=1` (steps show "Picking the 8 best passages"); both answers were not flagged, and the TMP deflection answer (27.42 in, offset 14 ft, 40 mph) is right.
- The guard compares the question's words only in labelled rows (a pipe table's header rows look like data rows), and only the numbers in pipe rows. Column labels are not checked.
- The held-out run for the `TOP_K` decision is the coordinator's.
