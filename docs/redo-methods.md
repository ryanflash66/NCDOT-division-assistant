# How the table and figure retrieval was redone: methods (DAR-652, DAR-660)

This is the methods record for the redo of the NCDOT division assistant's retrieval (Linear DAR-652 and its sub-tickets DAR-653 to DAR-659, plus the citation fix in PR #42). It is written for Dr. Namian first: a plain-language summary, then the technical detail. The decision-by-decision record, with every rejected option, is [`docs/redo-decision-log.md`](redo-decision-log.md) (D1 to D18). The per-ticket reports are in [`docs/redo-reports/`](redo-reports/).

The same text is published as a Claude Doc: [Table and figure retrieval redo: methods](https://claude.ai/artifact/USsSxZ2LkG7KnkTWB9HiFV).

Every rate in this document is given as a count, then its 95% interval. Section 2 explains how to read them.

## 1. Summary in plain language

**What was wrong.** The assistant answers a question from one NCDOT division's manuals and cites the document and page. Dr. Namian found answers that named the right manual but the wrong page. There were two causes:
- **Some citations were right but looked wrong.** The link opened the PDF at its 37th page, while the paper copy says "Page 13" there. Readers check the printed number.
- **Some were real misses,** mostly in tables and drawings. The text extraction lost which header a number sat under, cut tables at page breaks, and could not read scans or sideways pages well.

An earlier fix (DAR-651) had raised a hand-picked set of 15 image and table questions from 4 to 14 right. That set was also the one the fix was tuned on, so it could not show whether the fix worked in general. This redo started over against published practice and a page-by-page audit of all 60 PDFs.

**What was done.**
- We wrote 280 test questions with known answers and pages, and locked 232 of them away from tuning.
- Every citation now shows the printed page next to the PDF page.
- Tables are stored row by row with their headers and units, and tables that run over a page break are joined.
- Captions and table numbers ("Table 3-2") are searchable on their own.
- Scans are read again in other orientations when the first reading is poor, and every figure gets a searchable caption entry.
- Numbers in an answer are checked against the cited page.
- An answer that cites nothing is asked again for its source.
- Three other PDF readers and four reranker variants were tested on our own pages and questions; none was clearly better, so the current ones were kept.

**What it achieved** (232 locked questions, before and after):
- The cited page was right 120 of 190 times, against 94 of 185.
- The printed page shown was right 84 of 147 times; before, no printed page was shown (0 of 145).
- The value and the page were both right 117 of 204 times, against 93 of 204.
- The value was right 183 of 204 times, against 179 of 204. That difference is too small to call real.
- The later citation fix took the cited page from 27 of 39 to 37 of 39 right, but that was measured only on the 48 tuning questions.

**What is still wrong.**
- 8 of 232 locked answers gave a wrong number with a citation. In all 8 the model read the wrong cell or row of the right table, and the number check cannot catch that.
- 14 of 204 answerable locked questions were refused.
- After the final run we read the locked questions' misses to find their causes. A fix designed from them would look better on them than it is, so a fresh test set is needed before claiming a new after-number (DAR-661).
- The test questions were written and checked by script, not reviewed by an NCDOT engineer.

## 2. How to read the numbers

- **Count, then interval.** "120/190 (56–70%)" means 120 right out of the 190 cases where the measure applies. The range is the 95% Wilson interval: with this many questions, the true rate is probably inside it. When two ranges overlap a lot, the two numbers are not clearly different.
- **n changes between rows.** "Cited page right" counts only answers that were given and had a gold page; "value right" counts every answerable question. That is why one row says /190 and another /204.
- **Two splits.**
  - **Locked:** 232 questions (204 answerable, 28 that must be refused), frozen by a hash and never used to choose between options.
  - **Tuning:** 48 questions (41 answerable, 7 to refuse), used for every comparison.

  A number is from the locked split unless it says "tuning".
- **"Before"** ran the current answering code on the pre-redo index, with the new keyword field off and every chunk reranked. The old code has no test runner, so "before" means the old data and search, not the old prompts.
- **One run each.** The free models are not fully deterministic (temperature 0.1), so a rerun can move a count by one or two.

## 3. Results

### 3.1 Locked split, before and after the redo (PR #41)

From [`locked-set/baseline-pre-answers.md`](locked-set/baseline-pre-answers.md) and [`locked-set/final.md`](locked-set/final.md).

| | before | after |
|---|---|---|
| right page among the 5 passages the model reads | 183/204 (85–93%) | 183/204 (85–93%) |
| right page ranked first | 144/204 (64–76%) | 152/204 (68–80%) |
| value right | 179/204 (83–92%) | 183/204 (85–93%) |
| cited PDF page right | 94/185 (44–58%) | 120/190 (56–70%) |
| cited printed page right | 0/145 (0–3%) | 84/147 (49–65%) |
| value and cited page right | 93/204 (39–52%) | 117/204 (50–64%) |
| wrong value shown with a citation | 6/232 (1–6%) | 8/232 (2–7%) |
| answerable question refused | 19/204 (6–14%) | 14/204 (4–11%) |
| unanswerable question answered | 4/28 (6–31%) | 4/28 (6–31%) |

**Where the citation misses came from (after).** 61 of the 70 citation misses (77–93%) were answers that cited nothing at all. When the model did cite, the page was right 120 of 129 times (87–96%). Over both splits the same counts are 72 of 82 (79–93%) and 147 of 157 (89–97%). This finding is what the citation fix in 3.3 was built on.

### 3.2 Locked split by question type, before and after

Small groups have wide intervals; read these as direction, not proof.

| question type | items | value right | cited PDF page right | value and page right |
|---|---|---|---|---|
| text | 53 | 48/53 (80–96%) → 49/53 (82–97%) | 24/51 (34–60%) → 27/52 (39–65%) | 24/53 (33–59%) → 27/53 (38–64%) |
| table | 50 | 47/50 (84–98%) → 48/50 (87–99%) | 24/48 (36–64%) → 34/49 (55–80%) | 24/50 (35–61%) → 33/50 (52–78%) |
| figure | 13 | 11/13 (58–96%) → 11/13 (58–96%) | 4/11 (15–65%) → 10/12 (55–95%) | 4/13 (13–58%) → 10/13 (50–92%) |
| scanned page | 14 | 13/14 (69–99%) → 13/14 (69–99%) | 5/13 (18–64%) → 5/13 (18–64%) | 5/14 (16–61%) → 5/14 (16–61%) |
| rotated page | 14 | 8/14 (33–79%) → 11/14 (52–92%) | 6/9 (35–88%) → 6/11 (28–79%) | 6/14 (21–67%) → 6/14 (21–67%) |
| table over a page break | 13 | 13/13 (77–100%) → 12/13 (67–99%) | 8/13 (36–82%) → 9/12 (47–91%) | 8/13 (36–82%) → 9/13 (42–87%) |
| footnote | 13 | 10/13 (50–92%) → 8/13 (36–82%) | 6/10 (31–83%) → 7/10 (40–89%) | 6/13 (23–71%) → 5/13 (18–64%) |
| printed page named | 9 | 7/9 (45–94%) → 7/9 (45–94%) | 4/7 (25–84%) → 4/7 (25–84%) | 4/9 (19–73%) → 4/9 (19–73%) |
| units | 7 | 7/7 (65–100%) → 7/7 (65–100%) | 3/7 (16–75%) → 5/7 (36–92%) | 3/7 (16–75%) → 5/7 (36–92%) |
| cross-reference | 7 | 4/7 (25–84%) → 6/7 (49–97%) | 3/5 (23–88%) → 4/6 (30–90%) | 2/7 (8–64%) → 4/7 (25–84%) |
| duplicate pages | 6 | 6/6 (61–100%) → 6/6 (61–100%) | 6/6 (61–100%) → 6/6 (61–100%) | 6/6 (61–100%) → 6/6 (61–100%) |
| table number named | 5 | 5/5 (57–100%) → 5/5 (57–100%) | 1/5 (4–62%) → 3/5 (23–88%) | 1/5 (4–62%) → 3/5 (23–88%) |
| must be refused | 28 | refused 24/28 (69–94%) → 24/28 (69–94%) | | |

Footnote questions got worse: value right 10 → 8 of 13, and 2 of the 8 confident wrong answers are footnote questions (0 before). In both, the answer came from the table itself instead of the note under it that the question asks about (wztc-052, wztc-055). This is inside the intervals but is the one type that moved the wrong way.

### 3.3 Citation fix (PR #42), tuning split only

From [`locked-set/tuning-final2.md`](locked-set/tuning-final2.md) (before) and [`locked-set/tuning-cite2.md`](locked-set/tuning-cite2.md) (after). The locked split was not rerun, because its misses were read to design this fix.

| | before | after |
|---|---|---|
| cited PDF page right | 27/39 (54–81%) | 37/39 (83–99%) |
| cited printed page right | 21/35 (44–74%) | 28/35 (64–90%) |
| value right | 39/41 (84–99%) | 39/41 (84–99%) |
| value and cited page right | 27/41 (51–78%) | 37/41 (77–96%) |
| wrong value shown with a citation | 0/48 (0–7%) | 0/48 (0–7%) |
| answerable question refused | 2/41 (1–16%) | 2/41 (1–16%) |

## 4. How it works now (technical)

The assistant is a FastAPI app on Vercel (`hosted/`). The index is built offline by `prototype/ingest.py` and committed as `hosted/index/` (13,240 chunks from 58 documents in three divisions: Work Zone Traffic Control, Utilities, and Traffic Management and Signal Design).

### 4.1 Reading the PDFs (DAR-656, DAR-658)

- **Reader:** pymupdf4llm (PDF to Markdown), with table boxes from pymupdf-layout. Pages with no usable text layer go to RapidOCR (`--ocr`).
- **OCR orientation retry:** the page is first read in the orientation its text layer suggests. When that reading's confidence is low, or much of the text comes out sideways, the other three orientations are read too and the most confident upright reading is kept (`rag/ocr.py`). Low-confidence and rotated readings are flagged on the chunk.
- **Bake-off:** on 117 hard pages from 38 documents, the current reader got 24/30 hand-checked table cells right (63–90%), Docling 2.147 23/30 (59–88%), MinerU 4.1.7 22/30 (56–86%). The current reader also kept the most numbers (0.95 of the text layer's numbers, against 0.87 and 0.79) and was fastest (2.5 CPU s/page, against 19.3 and 6.2). It was kept for every page ([`extraction-bakeoff.md`](extraction-bakeoff.md)).

### 4.2 Tables (DAR-655)

- **Headers:** headers that span columns are filled forward; a rotated row header (the "Offset (ft)" cell on TMP Design Manual PDF p.37, attached to the first row only) is repeated on every row it covers.
- **Labelled rows:** besides the Markdown grid, each row is written as labelled text ("Offset (ft)=14 | Design Speed (mph): 40=27.42"). This is the common way to make table rows searchable.
- **Splitting:** a table that is too long for one chunk is split by rows; each part repeats the caption and header, and a label's rows stay together.
- **Tables over a page break:** joined into one chunk when page N ends with a table and page N+1 starts with one with the same columns, plus a repeated header, a "continued" caption, or boxes touching the page edges. On 20 hand-checked breaks the rule found 12 of 15 continuations (55–93%) with no wrong joins in 5 non-continuations; it was tuned on the same 20 breaks ([`table-merge-check.md`](table-merge-check.md)). A joined chunk cites both pages.
- **Flags:** every table chunk is checked for empty headers, wrong column counts, very little text, broken header text, a missing caption and rotation, and the build writes a report per document ([`build-report-final.json`](build-report-final.json)). 2,773 of 3,815 table chunks carry a flag; 1,717 carry one other than "no caption".

### 4.3 Figures and pages with no text (DAR-658)

- Each figure caption gets its own chunk: the caption, the lines near it and the drawing's OCR labels. No text is generated about a drawing, because a vision model for that needs Dr. Namian's approval.
- Of the pages the audit found with images and almost no text, or with most of their text lost, 6 image-only and 5 text-loss pages still have nothing useful indexed: 5 blank scans, 1 photo page, 4 tables with rotated headers or a form, and 1 sideways map legend ([`no-text-pages.md`](no-text-pages.md)).

### 4.4 Page numbers (DAR-654)

- The printed number is read from the PDF's page label, else from a number in the footer, else the header. It is accepted only where the numbers advance page by page through the document, which rejects sign codes, drawing sheet numbers and line numbers.
- A printed number was found on 5,107 of 5,924 pages (85–87%); 17 documents print none (scanned chapters, drawings, memos), and their citations show the PDF page only ([`page-identity.md`](page-identity.md)).
- Citations read "p.13 (PDF page 37)"; the link still opens the PDF at page 37.

### 4.5 Search (DAR-657)

Every search is limited to the target division's documents inside the search itself, so another division's text never reaches the reranker or the model.

1. **Meaning-based search:** the question is embedded with `BAAI/bge-small-en-v1.5` and compared with every chunk (top 40).
2. **Keyword search:** BM25 (k1 1.2, b 0.75) over two fields: the chunk text, and a boosted field (×1.5) holding captions, table, figure and section numbers, document codes and titles. A table or figure number named in the question is boosted ×2. These are boosts, never filters, so a chunk without the ID can still win (top 40).
3. **Fusion:** the two lists are merged by reciprocal rank fusion (k 60).
4. **Rerank:** the cross-encoder `Xenova/ms-marco-MiniLM-L-6-v2` rescores the text chunks only; table chunks keep their fused order (`RERANK_TEXT_ONLY=on`).
5. **Passages:** the top 5 go to the model; the next chunk is added for the top 2 hits, and consecutive chunks are merged so a rule that runs over a page break arrives whole.

Rejected after testing: ranking whole pages instead of chunks (`PAGE_AGGREGATION`), MiniLM-L-12, bge-reranker-base, jina-turbo, and 8 passages instead of 5 (decision log D9, D10, D15).

### 4.6 Answering and checks (DAR-659, PR #42)

- **Models:** free OpenRouter models in a fallback list (`nvidia/nemotron-3-ultra-550b-a55b:free`, then `nvidia/nemotron-3.5-super-vl:free`, then `google/gemma-4-31b-it:free`). The prompt holds only the target division's passages and asks for a `[n]` after each fact, or `NOT_IN_DOCUMENTS` when the passages don't answer.
- **Refusal retry:** a "not found" reply with a strong top passage is asked once more of the next model.
- **Citation repair:** an answer with no `[n]` is asked once more to cite its passage. The new reply is kept only if it cites a passage and keeps every number of the first answer. If it is still uncited, it is cited to the one passage holding all its numbers, only when exactly one passage does.
- **Number check:** every number with its unit must appear in the passages the answer cites, after normalising commas, fractions and unit spellings. If one is missing, the model is asked once more; if it is still missing, the answer is shown with an "unverified" warning.
- An OpenAI answering path was added afterwards (DAR-679, `LLM_PROVIDER=openai`). None of the numbers in this document were measured with it.

## 5. Test-set protocol (DAR-653)

**How the questions were chosen.**
- Candidate pages came from the corpus audit (section 6): pages with tables, rotated text, landscape pages, tables that run on, pages with no text layer, and pages whose printed number differs from the PDF index.
- Each question was written from the page itself, by the development assistant, one division at a time ([`locked-set/authoring-wztc.md`](locked-set/authoring-wztc.md), `-utilities.md`, `-tmsd.md`). Where an older development question already used a table, the locked item asks a different cell or a different table.
- Each expected value was checked by script against the page's text layer, or against its OCR text for scans. No NCDOT engineer reviewed the questions.
- 35 questions must be refused: other states' rules, years or values the documents don't cover, false premises.
- Each question names an asking division and a target division, as in real use: 263 of the 280 are asked from another division, 17 from the target division itself.

**What is locked.**
- 280 questions: Work Zone Traffic Control 100, Utilities 80, Traffic Management and Signal Design 100. 245 answerable, 35 to refuse; 195 distinct gold pages.
- The split is by hash of document and page (refusals hash the question), never by hand: 48 tuning, 232 locked.
- `evaluation/locked/LOCKED.sha256` freezes the locked items; `python -m evaluation.locked.run check` fails when any of them changes.
- The locked split is run only at release. Every such run is logged in [`locked-set/RUNS.md`](locked-set/RUNS.md): 10 so far, 8 retrieval-only and 2 with answers.

**How it is scored** (`evaluation/locked/score.py`, by rule, no AI judge):
- **Retrieval:** right document; right page ranked first; right page in the top 5.
- **Value:** the expected value appears in the answer after normalising units and number formats (`normalize.py`); a question may list other accepted forms.
- **Cited page:** every cited page is a gold page, checked separately for the PDF page and the printed page.
- **Strict:** value and cited PDF page both right.
- **Critical:** a wrong value shown with a citation, or an unanswerable question answered with a number.
- **Abstention:** answerable questions refused, unanswerable questions answered.
- Every rate gets a 95% Wilson interval. Results are broken down by split, division, question type, edge case and asker.

**Known weaknesses of the protocol.**
- An answer that also cites a correct second page is failed on "cited page"; 10 such misses need a hand check.
- The three division files name some edge cases differently (`rotated` and `rotated_text`, `cross_ref` and `cross_reference`); section 7 merges them.
- The locked misses were read after the final run (section 1), so the locked split is no longer a clean test.

## 6. Corpus audit (60 PDFs, 5,924 pages)

The audit (`.handoff/redo-nov4/corpus-audit.json`, made with `audit.py`) records for every page its text-layer characters, images, rotation, rotated characters, page label, header and footer lines, table boxes and "continued" markers.

| finding | pages |
|---|---|
| pages with a table | 965 |
| candidate tables that continue on the next page | 166 breaks (131 in two documents) |
| pages with rotated text | 380 (138 mostly rotated) |
| landscape pages | 395 |
| pages with images and almost no text layer | 187 |
| pages with a "continued" marker | 206 |
| pages with a PDF page label | 988 (840 of them differ from the PDF index) |
| pages with a printed page number found | 5,107 |

60 PDFs were audited; 58 are loaded by the assistant (two sit in their folders but no division lists them).

## 7. Edge-case matrix: what the test set covers

The 32 edge cases come from the evaluation research note (`.handoff/redo-nov4/C-eval-edgecases.md`, section 9a). This matrix is for the held-out set (DAR-661, DAR-718) and is generated by `python -m evaluation.heldout.matrix --report docs/heldout-set/baseline.json`. "Items" counts both splits; the results are the locked split, one run on Nov 11. A case is **covered** with 8 or more locked items, **thin** with 1 to 7, **not covered** with none.

| # | edge case | items | locked | value right | value and page right | must-refuse items | clarify | status |
|---|---|---|---|---|---|---|---|---|
| 1 | printed page differs from PDF page | 43 | 42 | 30/42 (56–83%) | 26/42 (47–75%) |  |  | covered |
| 2 | chapter page numbers ("5-13") | 41 | 37 | 29/35 (67–92%) | 28/35 (64–90%) |  | 2/2 (34–100%) | covered |
| 3 | appendix page numbers ("A-4") | 10 | 10 | 5/10 (24–76%) | 4/10 (17–69%) |  |  | covered |
| 4 | near-identical tables or pages | 14 | 13 | 10/13 (50–92%) | 9/13 (42–87%) |  |  | covered |
| 5 | value not in the first row or column | 29 | 27 | 22/27 (63–92%) | 22/27 (63–92%) |  |  | covered |
| 6 | table split over pages | 10 | 9 | 7/9 (45–94%) | 7/9 (45–94%) |  |  | covered |
| 7 | merged or multi-row headers | 10 | 9 | 6/9 (35–88%) | 6/9 (35–88%) |  |  | covered |
| 8 | rotated or landscape page | 14 | 14 | 7/13 (29–77%) | 7/13 (29–77%) |  | 0/1 (0–79%) | covered |
| 9 | scanned page | 36 | 34 | 26/34 (60–88%) | 25/34 (57–85%) |  |  | covered |
| 10 | degraded scan (skew, stamps) | 11 | 11 | 8/11 (43–90%) | 8/11 (43–90%) |  |  | covered |
| 11 | footnote or table note changes the value | 10 | 8 | 8/8 (68–100%) | 6/8 (41–93%) |  |  | covered |
| 12 | units | 40 | 38 | 33/36 (78–97%) | 32/36 (75–96%) |  | 2/2 (34–100%) | covered |
| 13 | ranges and thresholds | 28 | 26 | 23/26 (71–96%) | 23/26 (71–96%) |  |  | covered |
| 14 | conditional rules | 19 | 19 | 18/19 (75–99%) | 15/19 (57–91%) |  |  | covered |
| 15 | cross-reference ("see Table 4") | 9 | 9 | 7/9 (45–94%) | 4/9 (19–73%) |  |  | covered |
| 16 | answer needs two pages | 16 | 15 | 8/15 (30–75%) | 6/15 (20–64%) |  |  | covered |
| 17 | documents that give different values | 12 | 11 | 11/11 (74–100%) | 11/11 (74–100%) |  |  | covered |
| 18 | superseded edition | 9 | 9 | 9/9 (70–100%) | 7/9 (45–94%) |  |  | covered |
| 19 | multi-column reading order | 26 | 24 | 22/24 (74–98%) | 15/24 (43–79%) |  |  | covered |
| 20 | symbols and equations | 17 | 17 | 12/16 (51–90%) | 11/16 (44–86%) |  | 1/1 (21–100%) | covered |
| 21 | figure or drawing callouts | 17 | 17 | 10/15 (42–85%) | 10/15 (42–85%) |  | 1/2 (9–91%) | covered |
| 22 | forms and checklists | 11 | 11 | 8/11 (43–90%) | 7/11 (35–85%) |  |  | covered |
| 23 | out of scope (another state, another topic) | 9 | 7 |  |  | refused 7/7 (65–100%) |  | thin |
| 24 | in scope but not in the documents | 16 | 12 |  |  | refused 9/12 (47–91%) |  | covered |
| 25 | false premise | 15 | 15 | 10/15 (42–85%) | 10/15 (42–85%) |  |  | covered |
| 26 | numeric precision | 22 | 20 | 13/19 (46–85%) | 13/19 (46–85%) |  | 1/1 (21–100%) | covered |
| 27 | rephrased question | 23 | 19 | 18/18 (82–100%) | 16/18 (67–97%) |  | 0/1 (0–79%) | covered |
| 28 | same section in two divisions | 16 | 15 | 13/15 (62–96%) | 12/15 (55–93%) |  |  | covered |
| 29 | table-of-contents decoy | 15 | 15 | 15/15 (80–100%) | 15/15 (80–100%) |  |  | covered |
| 30 | list that runs over a page break | 15 | 14 | 8/14 (33–79%) | 6/14 (21–67%) |  |  | covered |
| 31 | question missing a needed variable | 15 | 14 |  |  |  | 9/14 (39–84%) | covered |
| 32 | revision marks, "reserved" | 18 | 14 | 1/2 (9–91%) | 1/2 (9–91%) | refused 11/12 (65–99%) |  | covered |
| — | table or figure number named in the question | 37 | 36 | 29/35 (67–92%) | 29/35 (67–92%) |  | 1/1 (21–100%) | covered |

- 31 of the 32 cases are covered; out of scope has 7 locked questions.
- The first version of this matrix, counted on the old locked set, had 20 covered, 3 thin and 9 not covered. It is in this file's history (PR #50) and in decision D18.
- "Must-refuse items" counts replies that declined, including a reply that says a section is reserved. "Clarify" counts answers that showed every case or asked for the missing variable.
- How the set was written and its limits: [`redo-reports/dar-661-heldout-set.md`](redo-reports/dar-661-heldout-set.md).

## 8. Limits and open problems

| limit | numbers | where it is handled |
|---|---|---|
| The held-out set is far from the targets | value right 201/242 (78–87%); cited PDF page right 207/237 (83–91%); confident wrong 31/286 (8–15%) | DAR-661 result; the fixes in DAR-662, 663, 664 and 717 are scored on this set |
| Answerable questions refused | 14/204 (4–11%) | DAR-662 |
| Wrong cell read from the right table, shown with a citation; the number check catches none | 8/232 (2–7%) | DAR-663: two models must agree on a number |
| The model reads 5 passages; the right page is often 6th to 8th | right page in the top 8 for 231/245 (91–97%, both splits) | DAR-664: 8 passages with a wrong-row guard |
| Page images are built but off in production (bundle size) | | DAR-665 |
| Footnote questions got worse | value right 10/13 (50–92%) → 8/13 (36–82%) | no ticket yet |
| Questions not reviewed by a domain expert | | no ticket yet |
| Scorer fails an answer that also cites a correct second page | 10 misses to hand-check | no ticket yet |
| Labelled table rows crowd the top 5 on some table pages | table questions, right page in top 5: 48/50 (87–99%) → 45/50 (79–96%) | no ticket yet |
| A header-joining rule could turn "Speed \| mph" into "Speedmph" | | no ticket yet |
| 6 image-only and 5 text-loss pages still have no useful text | | no ticket yet; the rotated ones need a text-layer fix |
| A paid vision model for drawings and failed scans | about USD 4.7 to 7.8 for 1,178 flagged pages at list price | Dr. Namian's decision; nothing was run |
| The OpenAI answering path (DAR-679) is not measured | | to be run on the DAR-661 set |

## 9. Sources

Each source is marked **independent** (academic or third-party measurement) or **vendor** (measured or claimed by the maker of the tool or model). Dates are as stated by the source. Our own measurements always decided; these were reasons to test.

| source | what we used it for | type |
|---|---|---|
| T2-RAGBench, arXiv 2506.12071 (June 2025) | a MiniLM reranker lowered scores on table questions: the reason for the reranker A/B (D10); hybrid search helps on tables | independent |
| Barnett et al., "Seven Failure Points When Engineering a RAG System", arXiv 2401.05856 (Jan 2024) | failure taxonomy behind the edge-case list | independent |
| REAL-MM-RAG, arXiv 2502.12342 (Feb 2025) | rephrased questions lower retrieval: edge case 27 | independent (IBM Research) |
| LIT-RAGBench, arXiv 2603.06198 | building in-scope unanswerable questions: edge case 24 | independent |
| Bowyer et al., "Position: Don't use the CLT in LLM evals with fewer than a few hundred datapoints", arXiv 2503.01747 (ICML 2025) | Wilson intervals instead of normal ones on small sets | independent |
| Miller, "Adding Error Bars to Evals", arXiv 2411.00640 (Nov 2024) | reporting every rate with its interval | vendor (Anthropic) |
| OmniDocBench, arXiv 2412.07626 and leaderboard | shortlist of PDF readers for the bake-off | independent benchmark; leaderboard rows partly self-submitted |
| MinerU2.5-Pro hard-table study, arXiv 2608.09842 (Aug 2026) | table extraction stays weak on hard tables | independent |
| LlamaIndex parsing benchmark, arXiv 2604.08538 | Docling's table score on default settings | vendor (LlamaIndex) |
| LED-Bench, arXiv 2610.19571 (Oct 2026), read via a summary | the best vision model answered 52.65% of large-format drawing questions; one model 31.77% on transportation drawings: a paid vision model is not a sure fix for drawings | independent |
| Docling chunking documentation (`repeat_table_header`) | repeating headers when a table is split | vendor (official docs) |
| Bruch et al., fusion functions, arXiv 2210.11934 (2022) | reciprocal rank fusion vs weighted fusion | independent |
| BM25S, arXiv 2407.03618 (Jul 2024) | tokenisation matters more than the BM25 variant | independent |
| "Drowning in Documents", arXiv 2411.11767 (2025) | rerank 20 to 50 candidates, not more | independent |
| `BAAI/bge-small-en-v1.5` model card | the embedding model | vendor |
| Jina reranker turbo/tiny announcement (Apr 2024) | candidate reranker | vendor |
| Nutrient, "PDF page labels" (updated Oct 2026) | how PDF page labels work | vendor (blog) |

**Three claims from the research notes were wrong and were corrected before use:**
1. Docling's "99.8% vs 66.6%" compares two chunking methods on 9 questions, not two PDF readers. It was not used.
2. MinerU's licence is Apache 2.0 with extra terms, not AGPL.
3. The reranker drop in T2-RAGBench is one small model on one benchmark, not a general finding.

## 10. Corrections kept visible

- **DAR-651 was a first pass.** Its 4 → 14 of 15 was measured on a small hand-picked set that the fix was also tuned on. After the redo that set scores 15 of 15, which is a regression check, not a result.
- **DAR-658's count of pages with no text was wrong.** "32 image-only and 7 text-loss pages" were counted against an index from before DAR-651's OCR. Against the pre-redo index the audit leaves 6 and 5, and the redo fixed none of them.
- **Two reports counted joined tables under their first page only,** so 25 pages looked as if they had lost all their text. Both reports were fixed; no page lost its text.
- **Earlier ticket comments mixed the splits.** Some gave numbers over all 280 questions (for example value right 221/245 and cited page right 147/229). This document uses the locked split unless it says otherwise.

## 11. Reproduce

Windows, from the repository root, with `OPENROUTER_API_KEY` in `.env`. The commands, the commit of every run and every shipped setting are in the decision log's "How to reproduce" section. Each per-ticket report in [`redo-reports/`](redo-reports/) gives its own command, commit and raw results file.

```bash
.venv\Scripts\python -m pytest tests/
.venv\Scripts\python -m evaluation.locked.run check
.venv\Scripts\python -m evaluation.locked.run run --label tune-check --split tuning --stage all
```
