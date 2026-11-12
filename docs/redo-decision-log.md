# Decision log: the table and figure retrieval redo (DAR-652)

This log records how the NCDOT division assistant's retrieval was redone (Linear DAR-652 and its sub-tickets DAR-653 to DAR-659). For every decision it gives:
- the question we were trying to settle;
- the options, including the rejected ones;
- the evidence;
- what we chose and why;
- what would change our mind;
- what went wrong or surprised us.

Failures are kept in.

## Summary in plain language

- **The problem.** Dr. Namian found answers that cited the right manual but the wrong page. Some citations were in fact correct but looked wrong: the page number printed on the paper differs from the PDF reader's page number. Others were real misses, mostly in tables and drawings that the text extraction read badly.
- **Fixed:**
  - Every citation now shows the printed page next to the PDF page.
  - Tables are stored row by row with their labels.
  - Tables that run over a page break are joined.
  - Captions and table numbers are searchable.
  - Numbers in an answer are checked against the cited page.
  - An answer that cites nothing is asked again for its source.
- **What we measured.** We wrote 280 questions with known answers and pages, and split them into 48 for tuning and 232 that are locked. On the locked questions, after versus before:
  - The value was right 183 of 204 times, against 179.
  - The cited page was right 120 of 190 times, against 94.
  - Both the value and the page were right 117 of 204 times, against 93.
- **Since then:** the citation fix took the cited page from 27 of 39 to 37 of 39 right, measured on the 48 tuning questions only.
- **What is still wrong:**
  - 8 of 232 locked answers state a wrong number with a citation: the model read the wrong cell of the right table.
  - 14 of 204 answerable locked questions are refused.
  - We read the locked questions' misses to find their causes, so they no longer give a clean after-number. A fresh set is next (DAR-661).

## How to read the numbers

- **Count, then interval.** "120/190 (56–70%)" means 120 right out of 190 cases where the measure applies. The range is the 95% Wilson interval: with this many questions, the true rate is probably inside it. Two numbers whose ranges overlap a lot are not clearly different.
- **The two splits.**
  - **Locked split:** 232 questions, 204 of them answerable. It is frozen by a hash (`evaluation/locked/LOCKED.sha256`) and never used to choose between options.
  - **Tuning split:** 48 questions, 41 answerable. Options are compared here.

  Unless a number says "tuning", it is from the locked split, one run each.
- **Metrics:**
  - **"Right page in top 5":** search found a chunk from the right page among the 5 passages the model reads.
  - **"Value right":** the answer contains the expected value after normalising units and number formats.
  - **"Cited page right":** every page the answer cites is the expected page.
  - **"Strict":** the value and the cited page are both right.
  - **"Confident wrong answer":** a wrong value shown with a citation.
- **Baseline caveat.** The "before" numbers ran the new answering code on the old index, with the new keyword field off and every chunk reranked. The old code has no test runner. So "before" is the old data and search, not the old prompts.

## Results table (locked split, one run each)

From `docs/locked-set/baseline-pre-answers.md` and `docs/locked-set/final.md`, section "By stratum / Split". 204 answerable questions and 28 unanswerable ones.

| | before the redo | after PR #41 |
|---|---|---|
| right page in top 5 | 183/204 (85–93%) | 183/204 (85–93%) |
| right page first | 144/204 (64–76%) | 152/204 (68–80%) |
| value right | 179/204 (83–92%) | 183/204 (85–93%) |
| cited PDF page right | 94/185 (44–58%) | 120/190 (56–70%) |
| cited printed page right | 0/145 (0–3%) | 84/147 (49–65%) |
| value and cited page right | 93/204 (39–52%) | 117/204 (50–64%) |
| confident wrong answer | 6/232 (1–6%) | 8/232 (2–7%) |
| answerable question refused | 19/204 (6–14%) | 14/204 (4–11%) |
| unanswerable question answered | 4/28 (6–31%) | 4/28 (6–31%) |

PR #42 (citation fix) was measured on the tuning split only: see D15.

---

## D1. How do we measure whether a change helps? (DAR-653)

- **Question:** Can we trust a before/after number at all?
- **Options:**
  - Keep the two hand-picked sets used in DAR-651: 15 image/table questions and 83 known-page questions.
  - Grade with an AI judge.
  - Write a larger set with known pages and grade it by rule.
- **Evidence:**
  - On 15 questions, one question is worth 6.7 percentage points, and those 15 were also the ones the DAR-651 fixes were tuned on.
  - A rule-based scorer gives the same grade every time and needs no paid model.
- **Chose:**
  - 280 questions (wztc 100, utilities 80, tmsd 100): 245 answerable, 35 that must be refused.
  - Each answerable question records the gold document, PDF page, printed page and value.
  - Split by hash into 48 tuning and 232 locked; the locked items are frozen with `LOCKED.sha256`.
  - A rule-based scorer with Wilson intervals (`evaluation/locked/score.py`).
  - Every run that touches the locked split is logged in `docs/locked-set/RUNS.md`.
- **Rejected:**
  - The 15/83 sets as the result: too small and already tuned on.
  - An AI judge as the main grader: it isn't deterministic, and the better judges are paid.
- **Would change our mind:** if open-ended answers became common, rules can't grade them, and a judge checked against hand grades would be needed.
- **Went wrong / surprised us:**
  - **Inconsistent edge-case labels.** The three division files label the same case differently (`rotated` vs `rotated_text`, `cross_ref` vs `cross_reference`), so edge-case counts split across labels.
  - **Scorer too strict on extra pages.** An answer that also cites a correct second page is failed; 10 such misses need a hand check.
  - **Locked split run 10 times.** That is 8 retrieval-only runs (the baseline, the final ranking and 6 reranker variants) and 2 answer runs (before and after), all logged in `RUNS.md`. The variant runs only reported options already picked on the tuning split (D10).
  - **Locked set no longer clean.** After the final run, we read the locked misses to find their causes (D15). See D17.

## D2. Printed page numbers in citations (DAR-654)

- **Question:** Why did a correct citation ("page 37") look wrong to Dr. Namian?
- **Options:**
  - Keep the PDF index only.
  - Use the PDF's own page labels only.
  - Read the number printed on the page.
- **Evidence:**
  - Only 988 of 5,924 pages have a PDF page label.
  - 840 of those labels differ from the PDF index.
  - Reading footers and headers as well, with a check that the numbers run in sequence through the document, found a printed number on 5,107 of 5,924 pages (86%).
  - Source: `docs/page-identity.md`.
- **Chose:**
  - Find the number from the PDF label first, then the footer, then the header, accepted only when it advances page by page.
  - Store it on every chunk.
  - Show "p.13 (PDF page 37)" in the answer, the API and the Sources panel; the link still opens the PDF at page 37.
- **Effect:** cited printed page right went from 0/145 to 84/147 (49–65%) on the locked split.
- **Rejected:** labels only, which would cover just 17% of pages.
- **Would change our mind:** if readers find the two numbers confusing, show the printed one only.
- **Surprised us:** 17 documents print no page number at all (scanned chapters, drawings, memos). Their citations show only the PDF page.

## D3. Page images in the Sources panel (DAR-654)

- **Question:** Should the reader see the cited page as an image?
- **Chose:** built it, but switched it on only with `RENDER_PAGES=1`. It is off in production.
- **Why off:** the rendered pages add to the Vercel bundle, which has a 500 MB limit and was about 340 MB before this work.
- **Open:** DAR-665.

## D4. How tables are written into the index (DAR-655)

- **Question:** How do we stop a table row losing its unit and header? Example: TMP Design Manual PDF p.37, where the rotated "Offset (ft)" header was attached to the first row only.
- **Options:**
  - Keep the plain Markdown grid.
  - Fill spanned headers forward and repair rotated row headers.
  - Also write each row as labelled text ("Offset (ft)=14 | … | Design Speed (mph): 40=27.42"), the common practice for searching tables.
- **Evidence:**
  - Tests show p.37, p.38 and the turn-radius table now return labelled rows.
  - Locked set, right page in top 5 on table questions: 53/58 after against 55/58 before (both splits). Value right on table questions improved.
- **Chose:** all three. Splits repeat the caption and header and keep a label's rows together.
- **Went wrong / surprised us:**
  - **Crowding.** The labelled rows add chunks per table page. On several questions one page filled 3 of the 5 slots and pushed the gold page out, so the "table questions improve or stay equal" target was not met on retrieval (inside the intervals).
  - **Header-joining risk.** A rule that rejoins header words cut by a column boundary reads `17a | x` as one word. It would also join a real "Speed | mph" header into "Speedmph". This is not yet fixed.
- **Would change our mind:** if a fresh set shows the crowding costs more than the labels gain, keep one labelled chunk per table page (see D11).

## D5. Tables that continue on the next page (DAR-655)

- **Question:** Should a table that runs over a page break be joined into one chunk?
- **Evidence:**
  - The corpus audit found 166 candidate breaks. 131 of them are in two documents: the Traffic Services Legal Guide and Division 11 Combined.
  - 20 breaks were opened by hand: 15 continue, 5 don't.
  - The first rule found 7 of the 15 continuations (precision 1.00, recall 0.47). After tuning it found 12 of 15, with no wrong merges (precision 1.00, recall 0.80). Source: `docs/table-merge-check.md`.
- **Chose:** the tuned rule. A joined chunk keeps both pages and cites "pp.13–14 (PDF pages 37–38)".
- **Caveat:** the rule was tuned on the same 20 breaks it was scored on, so 0.80 is optimistic.
- **Surprised us:** two of our own reports counted a joined table under its first page only, so 25 pages looked as if they had lost all their text: the build report, fixed in PR #41, and `docs/no-text-pages.md`, fixed with this log. None had.

## D6. Flag bad tables at index time instead of fixing them (DAR-655)

- **Chose:** flag empty headers, wrong column counts, very little text, broken header text, a missing caption and rotated pages, and write a build report per document (`docs/build-report-final.json`).
- **Result:**
  - 2,773 of 3,815 table chunks are flagged.
  - 1,717 have a flag other than "no caption", mostly empty headers (1,382).
- **Why flag only:** the flags show where extraction is weak. Fixing each class is separate work, and some may need a vision model (D7).

## D7. Which PDF reader (DAR-656)

- **Question:** Is our reader (pymupdf4llm with RapidOCR) the right one, or would Docling or MinerU do better on our hardest pages?
- **Evidence:** 117 hard pages from 38 documents, all run on CPU (`docs/extraction-bakeoff.md`):

| reader | table cells right (30 hand-checked) | numbers kept vs text layer | no-text pages read | CPU seconds per page |
|---|---|---|---|---|
| pymupdf4llm + RapidOCR (kept) | 24/30 | 0.95 | 21/26 | 2.5 |
| Docling 2.147 | 23/30 | 0.87 | 22/26 | 19.3 |
| MinerU 4.1.7 (medium) | 22/30 | 0.79 | 21/26 | 6.2 |

  MinerU's high mode (a vision model) took up to 1,219 s on one page and was no more accurate.
- **Chose:** keep the current reader for every page. Neither alternative wins any class of page.
- **Rejected:** Docling and MinerU. Both lose more numbers and are slower.
- **Not decided by us:** a paid vision model for drawings and failed scans. At list price that is about USD 4.7 to 7.8 for the 1,178 flagged pages. It needs Dr. Namian's approval and nothing was run.
- **Corrected claim:** a research note said Docling scores "99.8% vs 66.6%". That figure compares two chunking methods on 9 questions, not two PDF readers, so it was not used.

## D8. A keyword field for captions and table numbers (DAR-657)

- **Question:** How do we find "Table 3-2" or a document code like 04091 when meaning-based search treats them as noise?
- **Options:**
  - Keep the single keyword field.
  - Add a separate, boosted field with captions, table, figure and section numbers, document codes and titles (a "BM25F" field).
  - Filter by the ID instead of boosting.
- **Evidence:** on the 83 known-page development questions, right page in top 5 was 74/83 with the keyword search off and 77/83 with it on. Source: `docs/page-aggregation.md`, development set.
- **Chose:** the boosted field (boost 1.5), plus question parsing that boosts a named ID twice. It is a boost, never a filter, so a chunk without the ID can still win.
- **Rejected:** filtering. One wrong ID read from the question would hide the right page.

## D9. Rank whole pages instead of chunks? (DAR-657)

- **Question:** When a table is split into several chunks, should the page be scored as a whole?
- **Evidence:**
  - Locked split, right page first / in top 5: page-max 147 / 177, page-sum 138 / 178, no aggregation 147 / 180.
  - Tuning split: also no better.
  - Sources: `docs/locked-set/reranker-pick.md`, `docs/page-aggregation.md`.
- **Chose:** keep it off (`PAGE_AGGREGATION=off`).
- **Why it failed:** the top page's second chunk takes a slot that a different, sometimes correct, page held before.
- **Would change our mind:** the untested variant (sum, with at most one chunk per page) is worth a try against the crowding in D4.

## D10. Which reranker (DAR-657)

- **Question:** Does the reranker hurt on tables? A research note cited one benchmark where a similar reranker lowered scores.
- **Options:**
  - No reranker.
  - MiniLM-L-6 on every chunk (the old default).
  - MiniLM-L-6 on text chunks only.
  - MiniLM-L-12.
  - bge-reranker-base.
  - jina-turbo.
- **How we picked:** on the tuning split first, then reported once on the locked split.
- **Tuning evidence** (right page first / in top 5, 41 answerable): text-only 33 / 39, old default 32 / 38, no reranker 31 / 39, L-12 32 / 38.
- **Locked split** (`docs/locked-set/reranker-pick.md`):

| variant | right page first | right page in top 5 |
|---|---|---|
| MiniLM-L-6, every chunk | 147/204 (66–78%) | 180/204 (83–92%) |
| no reranker | 136/204 (60–73%) | 183/204 (85–93%) |
| **MiniLM-L-6, text chunks only (chosen)** | **152/204 (68–80%)** | **183/204 (85–93%)** |
| MiniLM-L-12 | 147/204 (66–78%) | 180/204 (83–92%) |

- **Chose:** `RERANK_TEXT_ONLY=on`. Tables keep their search order and are not sent to the reranker. The gain is inside the intervals: small, not proven.
- **Rejected:**
  - MiniLM-L-12: the same results at about 6 times the size.
  - bge-reranker-base: too large for the Vercel bundle.
  - jina-turbo: ranked below no reranker on the development sets.
- **Corrected claim:** the research note's "reranker drop" is one small model on one benchmark. It was a reason to test, not evidence on its own.
- **Surprised us:** timings were measured on a machine at 100% CPU, so `docs/reranker-ab.md` gives relative times only.

## D11. Pages with no text: scans, drawings, sideways pages (DAR-658)

- **Question:** How do we search pages whose text layer is empty or sideways?
- **Options:**
  - OCR as before.
  - OCR that retries other orientations when the first reading is poor.
  - Add a caption chunk for each figure.
  - Have a vision model describe each drawing (paid).
- **Chose:**
  - OCR with the orientation retry.
  - Flags on low-confidence and rotated OCR (17 chunks).
  - A figure chunk per caption, holding the caption, nearby lines and the drawing's OCR labels.
  - No generated descriptions, since those need Dr. Namian's approval.
- **Evidence:** locked and tuning splits, right page in top 5: scan 17/19 against 16/19 before; figure 17/17 against 16/17.
- **Correction to the DAR-658 ticket comment.** The "32 image-only and 7 text-loss pages" were counted against an index from before DAR-651. Against the pre-redo index (after DAR-651's OCR), the audit leaves 6 image-only and 5 text-loss pages, and the redo fixed none of them (`docs/no-text-pages.md`, regenerated against the final index):
  - 5 are blank scanned pages.
  - 1 is a photo page.
  - 4 are tables with rotated header text, or a form whose boxes are dropped.
  - 1 is a sideways map legend.

  The rotated ones need a text-layer fix, not OCR.

## D12. Checking the numbers in an answer (DAR-659)

- **Question:** In a safety setting, a wrong number is worse than "I could not find it". Can we catch one?
- **Chose:**
  - Every number with its unit in the answer must appear in the passages the answer cites, after normalising commas, fractions and unit spellings.
  - If not, the model is asked once more.
  - If the number is still missing, the answer is shown with an "unverified" warning.
- **Evidence:**
  - A test with a deliberately wrong number is caught.
  - The turn-radius question was right 3 of 3 times.
  - Locked split: 2 of 132 cited answers flagged, and both flags were false alarms.
  - 8 of 232 answers were confident and wrong, and the check caught none of them. In all 8 the wrong number is on the cited page; the model read the wrong cell or row.
- **Lesson:** the check catches made-up numbers, not misread tables. That needs a second opinion (DAR-663).

## D13. Merge 16 pull requests on one branch, rebuild once

- **Question:** Merge the 16 sub-ticket PRs one by one, or together?
- **Chose:** one integration branch (PR #41), one full index rebuild, one before and one after run.
- **Why:** many PRs touch the same files (`ingest.py`, `loader.py`, `retrieval.py`). Merging one at a time would mean 16 rebuilds of about 44 minutes each, and numbers measured on in-between states.
- **Went wrong:**
  - The first rebuild was killed when the session ended; it was rerun detached.
  - Two merges needed hand fixes: the OCR flags and the table flags, and the figure chunks' printed pages.

## D14. Answers that cite nothing (PR #42)

- **Question:** Why was the cited page right only 120/190 times on the locked split?
- **Evidence:** reading the final run's misses:
  - **Locked split:** 61 of the 70 citation misses, 61/70 (77–93%), cited nothing at all. When the model did cite, the page was right 120/129 (87–96%).
  - **Both splits:** 72/82 (79–93%) and 147/157 (89–97%). These are the figures the earlier ticket comments quoted.
  - The free model replied with the bare value ("5 feet"). Over both splits the value was right in 69 of the 72 uncited answers.
- **Options:**
  1. Cite the best-ranked passage that contains the answer's numbers. Replayed on the cached answers: 43 right pages, 19 wrong.
  2. The same, but only when exactly one passage contains them: 33 right, 1 wrong, 38 left uncited.
  3. Ask the model once more to cite its passage.
- **Chose:** 3, then 2 as a fallback.
- **Rejected:** 1, which gave the wrong page 19 times in 62.
- **Went wrong:** asked again, the model sometimes re-read the table and changed a right value (Detail 3-2A: 5 ft became 6 ft, 330 ft became 290 ft; tuning split). Fix: the second answer is kept only if it keeps every number of the first.
- **Tuning split only** (`docs/locked-set/tuning-final2.md`, `tuning-cite2.md`):

| | before | after PR #42 |
|---|---|---|
| cited PDF page right | 27/39 (54–81%) | 37/39 (83–99%) |
| value right | 39/41 (84–99%) | 39/41 (84–99%) |
| value and cited page right | 27/41 (51–78%) | 37/41 (77–96%) |
| confident wrong answer | 0/48 (0–7%) | 0/48 (0–7%) |

- **Caveat:** 39 questions are few, and the interval runs from 83% to 99%. The locked split was not rerun: its misses were read to design this fix, so it would flatter it (D17).

## D15. Give the model 8 passages instead of 5?

- **Evidence:**
  - The right page is in the top 8 for 231 of 245 answerable questions (both splits), and in the top 40 for 241.
  - On the tuning split, 8 passages gave 0 refusals instead of 2.
  - But one first answer read the wrong row of Detail 3-2A, a confident wrong answer (1/48 against 0/48). Source: `docs/locked-set/tuning-cite2-k8.md`.
- **Chose:** keep `TOP_K=5`.
- **Would change our mind:** a guard against wrong-row reads (DAR-664, with DAR-663).

## D16. One gold-label fix on the tuning split

wztc-088 expected "2 submissions", and the scorer failed the answer "2". "2" was added as an accepted answer. This is a tuning item; the locked items are unchanged, and `python -m evaluation.locked.run check` passes.

## D17. The locked set is no longer a clean test

- **Question:** Can the locked split give the after-number for PR #42?
- **What happened:** to find why citations failed, we read the locked misses after the final run. Any fix designed from them will look better on those questions than it really is.
- **Chose:**
  - Report #42 on the tuning split only.
  - Write a fresh held-out set before claiming an after-number (DAR-661).
- **Related:** DAR-651's 15-question image/table set (15/15 after the redo) is only a regression check: it was the set DAR-651 was tuned on. It is not a result.

## D18. The methods document and one report per ticket (DAR-660)

- **Question:** Can a reader with no context follow how the redo was done, without reading every ticket?
- **Chose:**
  - `docs/redo-methods.md`: the plain summary first, then the pipeline, the test-set protocol, the corpus audit, the edge-case matrix (what the test set covers), limits, and sources marked independent or vendor. The same text is published as a Claude Doc tab.
  - `docs/redo-reports/`: one short report per sub-ticket, with before and after on the same questions, the raw results files, and the command and commit.
- **Evidence it needed:** the edge-case matrix was counted from `final.json`, merging the labels the division files spell differently. 20 of the 32 edge cases in the research note have 8 or more locked questions, 3 have 1 to 7, and 9 have none (degraded scans, ranges, superseded editions, multi-column order, symbols, duplicate sections across divisions, lists over a page break, missing variables, revision marks).
- **Surprised us:**
  - **Footnote questions moved the wrong way:** value right went from 10/13 (50–92%) to 8/13 (36–82%) on the locked split, and 2 of the 8 confident wrong answers are footnote questions (0 before). That is inside the intervals, but it is the one type that got worse.
  - **Not every question is cross-division:** 17 of the 280 are asked from the target division itself.
- **Not done:** nothing was rerun for this entry; every number comes from the runs already logged in `docs/locked-set/RUNS.md`.

## D19. A held-out test set, and the first clean number (DAR-661, DAR-718)

- **Question:** How good is the assistant on questions nobody tuned for?
- **Chose:**
  - A new set, `evaluation/heldout/`: 311 questions (286 locked, 25 tuning) on pages no older test set uses, written from the PDF pages by three authors who could not see the old questions, any run report or the index.
  - The 12 edge cases the old set had no or few questions for go into the same set before the freeze (DAR-718), so there is one clean set, not two.
  - A `behaviour` field per question: answer, refuse, correct a false premise, or ask for a missing variable. Lists need every item. Missing-variable questions get their own score and stay out of the value rate.
  - One fixed tag per edge case, enforced, so the coverage matrix is generated and not merged by hand.
  - Frozen by hash in commit 34eb374 before the one scored run.
- **Evidence (locked split, one run, free models):**
  - value right 201/242 (78–87%); cited PDF page right 207/237 (83–91%); both right 180/242 (69–79%).
  - confident wrong 31/286 (8–15%); answerable refused 19/256 (5–11%); must-refuse answered 4/30 (5–30%).
  - missing variable handled 9/14 (39–84%); no answer without a citation.
  - 31 of 32 edge cases have 8 or more locked questions.
- **Surprised us:**
  - **Confident wrong answers are much more common than the old set showed** (8/232 there). The new set has more hard cases, so the two are not a before and after, but 25 of the 31 are on ordinary answer questions.
  - **The citation fix held:** 72 of the old set's 82 citation misses were uncited answers; here none is uncited.
  - **Lists over a page break:** 6 of 14 came back cut short, with a citation.
  - **Superseded editions and marked-up revisions are rare in these documents:** 9 real old/new pairs in all, and no strikethrough or revision bars.
- **Not done:**
  - The OpenAI path is not scored: the key is only in Vercel.
  - No person reviewed the questions; 32 gold values were read off page images with no machine check.
  - The tuning split is small (25), because the authors chose pages that hash to the locked side for the priority cases.
  - Out of scope has 7 locked questions, one short of the bar.
- **Report:** `docs/redo-reports/dar-661-heldout-set.md`; run `docs/heldout-set/baseline.md`.

## Corrected claims from the research notes

Three claims in `.handoff/redo-nov4/` were checked against the original sources and corrected before use:
1. **Docling "99.8 vs 66.6":** a chunking comparison on 9 questions, not a reader comparison (D7).
2. **MinerU's licence:** Apache 2.0 with extra terms, not AGPL.
3. **The reranker drop:** one small model on one benchmark (T2-RAGBench, arXiv 2506.12071), not a general finding (D10).

## How to reproduce

Windows, from the repository root, with `OPENROUTER_API_KEY` in `.env`. The answer runs use free models; the free daily quota is shared, so a run may stop and resume.

```bash
.venv\Scripts\python -m pytest tests/
.venv\Scripts\python -m evaluation.locked.run check
.venv\Scripts\python -m evaluation.locked.run run --label tune-check --split tuning --stage all
.venv\Scripts\python -m evaluation.locked.run run --label tune-retrieval --split tuning --stage retrieval
.venv\Scripts\python -m prototype.ingest --ocr --reuse hosted/index
.venv\Scripts\python -m prototype.build_report --index hosted/index --markdown
.venv\Scripts\python -m prototype.no_text_pages --baseline <pre-redo index> --index hosted/index
```

- **The locked split** is run with `--split locked` (or `all`), at release only. Each such run is appended to `docs/locked-set/RUNS.md`.
- **Changed answering code** gets `--tag NAME`, so cached answers are not reused. `TOP_K` other than 5 is added to the cache key automatically.

| run | commit | index | settings |
|---|---|---|---|
| before (`baseline-pre`, `baseline-pre-answers`) | d0868dc, e7574ac | pre-redo index, 10,746 chunks (main at 8feefe6) | keyword field off, every chunk reranked |
| after #41 (`final`) | e7574ac | `hosted/index`, 13,240 chunks | defaults below |
| reranker variants (`locked-retrieval-*`) | d60f7d0 | same | `RERANK_MODEL`, `RERANK_TEXT_ONLY`, `PAGE_AGGREGATION` per variant |
| #42 tuning (`tuning-final2`, `tuning-cite2`, `tuning-cite2-k8`) | 3d0adb9 | same | `--tag cite2`; `TOP_K=8` for the last |

Shipped defaults:

| setting | value |
|---|---|
| `TOP_K` | 5 |
| `RERANK_CANDIDATES` | 40 |
| `KEYWORD_SEARCH` | on |
| `KEYWORD_FIELD_BOOST` | 1.5 |
| `KEYWORD_ID_BOOST` | 2 |
| `RERANK_TEXT_ONLY` | on |
| `PAGE_AGGREGATION` | off |
| `FUSION_WEIGHTS` | 1,1 |
| RRF k | 60 |
| BM25 k1 / b | 1.2 / 0.75 |
| `RENDER_PAGES` | off |

Models: `nvidia/nemotron-3-ultra-550b-a55b:free`, then `nvidia/nemotron-3.5-super-vl:free`, then `google/gemma-4-31b-it:free`.

## Known limits and open risks

Each item maps to a Sprint 5 ticket.

| limit | numbers | ticket |
|---|---|---|
| No clean after-number: the locked split was read for causes | — | DAR-661: a fresh held-out set of 200+ questions |
| Answerable questions refused | 14/204 locked (4–11%) | DAR-662 |
| Wrong cell read from the right table, shown with a citation | 8/232 locked (2–7%), none caught by the number check | DAR-663: two-model agreement on numbers |
| The model sees 5 passages while the right page is often 6th to 8th | in top 8 for 231/245 (both splits) | DAR-664: 8 passages with a wrong-row guard |
| Page images not in production | — | DAR-665 |

Also open, without a ticket yet:
- **Scorer:** it fails an answer that also cites a correct second page (10 misses to hand-check).
- **Edge-case labels:** inconsistent across divisions.
- **Header rule:** the "Speed | mph" joining risk (D4).
- **Table crowding:** labelled rows crowd the top 5 (D4).
- **Unfixed pages:** the 5 text-loss and 6 image-only pages (D11).
- **Paid vision model:** the decision is with Dr. Namian (D7).
