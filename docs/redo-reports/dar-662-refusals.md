# DAR-662: answerable questions the assistant refuses

**What changed.** When the model replies that the passages don't answer the question, the next model is asked once more, and it now also gets up to 15 more passages: the chunks ranked after the top 5, in rank order from the reranker's 40 candidates, with at most 2 table chunks per page and nothing the first passages already showed. The new passages are numbered after the first five ([6], [7], ...), and the model is told to look again at all of them, including table cells, figure text and table notes. The retry now runs whenever the best reranker score is at least -2.0 (it was 1.0). The first answer still reads only the top 5 (`TOP_K` unchanged). Code: `hosted/divrag/answer.py` (`SECOND_LOOK_PASSAGES`, `SECOND_LOOK_RULE`, `Answerer._second_look`, `RETRY_MIN_SCORE`).

## Why: the 16 refusals of the final run, by cause

From `docs/locked-set/final.json` (both splits, items with `answerable` true and `refused` true), plus the NC-PCB question a user reported. The locked items were read only to find causes; they are not a measure of this fix.

Causes: **(a)** the right page was among the passages the model read, and both models still refused. **(b)** the right page (or the chunk with the answer) was not among them. **(c)** the retry rule kept the question from a second try. **(d)** the page has no useful text in the index.

"Rank" is where the chunk holding the answer comes in the reranked 40 candidates (retrieval only, same index and settings). "Top score" is the best reranker score of the top 5; the retry ran only at 1.0 or more. "Second look" says whether the new retry shows the chunk with the answer.

| item | split | type | rank of the answer | top score | cause | second look shows it |
|---|---|---|---|---|---|---|
| tmsd-002 | locked | table | 6 | -0.62 | b, c | yes |
| tmsd-022 | locked | rotated drawing | not in 40 | 4.12 | d: the drawing's text is garbled ("FIGU~~R~~E 1"); 575 is not in the index | no |
| tmsd-026 | locked | figure | 1 | 5.11 | d: the rating grid of Figure 1 is lost; the figure text has the tactic names and digits but not which cell holds which | no (already shown) |
| utilities-021 | locked | cross-reference | 12 (Section 2.7.6, p.69); the referring page p.137 is 2nd | 1.46 | b: the referred section is not in the top 5 | yes |
| utilities-028 | locked | footnote | 9 (footnote 2) | -1.61 | b, c | yes |
| utilities-060 | locked | text | 25 | 4.27 | b | no |
| wztc-019 | locked | table over a page break | 8: the 70 mph row is on p.41; the top 5 were all chunks of p.40 | 4.68 | b: the table's continuation did not reach the model | yes |
| wztc-026 | locked | rotated drawing | 11 | 1.80 | b | yes |
| wztc-029 | locked | rotated table | 5 | 2.24 | a: "WZTCU" is in the cell next to "Host national or regional work zone safety conferences" | already shown; the new rule asks to read table cells |
| wztc-034 | tuning | rotated table | 7 | 3.71 | b: 4 of the top 5 were chunks of one other table page (p.34) | yes |
| wztc-037 | tuning | scan | 12 | 0.48 | b, c | yes |
| wztc-039 | locked | scan | 19 | 3.08 | b | yes (table cap) |
| wztc-053 | locked | table note | 14: the CPI note under Table 12 (p.41) | 5.54 | b: the table reached the model, its note did not | yes |
| wztc-054 | locked | table note | 11 | -0.97 | b, c | yes |
| wztc-065 | locked | printed page named | 13 | 6.30 | b | yes |
| wztc-066 | locked | printed page named | not in 40 | 7.34 | b: "page 101" is a printed page; the search finds other "Best Practices Category" pages | no |
| NC-PCB dimensions (user report) | — | text | 34 (TMP Design Manual PDF p.32, printed p.8) | 2.25 | b: the top 12 were labelled-row chunks of one Standard Specifications table ("HIGH STRENGTH BOLTS WASHER DIMENSIONS", PDF p.518); the model read 2 merged passages, both of that table | yes (table cap) |

Summary over the 16: cause (a) 1, (b) 13 (4 of them also (c)), (d) 2. The second look shows the answer for 11 of the 16 (and wztc-029's was shown already) and for the NC-PCB question; it cannot help tmsd-022 and tmsd-026 (no text), utilities-060 (25th) and wztc-066 (not in the 40).

What these show about the old retry: it re-read the same 5 passages with the next model, and 12 of the 16 got that retry; all 12 refused again. In 14 of 16 the answer was not in those passages, so a second model could not find it.

Why the table cap: one table's labelled rows are split into many chunks that score alike (`RERANK_TEXT_ONLY` keeps tables at their fused rank). Without the cap, the next 15 ranks would miss the NC-PCB sentence (34th) and wztc-039 (19th); with the cap on all chunks of a page (not only tables), wztc-053's table note would be skipped, because its page already gave two table chunks.

**Why the bar moved from 1.0 to -2.0.** The reranker score does not separate the two kinds of question any more: on the tuning split, the 7 questions that must be refused had top scores -1.51, -1.45, 0.15, 0.55, 1.04, 2.05 and 3.96, and 4 of the refused answerable questions above had -1.61 to 0.48. -2.0 still keeps a refusal fast when nothing in the division is close.

## The NC-PCB dimensions question

- The page: TMP Design Manual (`hosted/documents/wztc/TMP Design Manual (Combined, No Links).pdf`), PDF page 32, printed page 8, section 5.4.1 NC Standard Portable Concrete Barrier: a "New Jersey Shape" freestanding pre-cast section, 10 ft long, 24 in wide at the base and 32 in high (about 3,900 lb).
- The question: "What are the NC-PCB dimensions?", asked of Work Zone Traffic Control from Utilities.
- Before (in-process, the pre-change retry): refused. The model read 2 passages, both the Standard Specifications washer-dimension table; the retry call failed on a free-model rate limit.
- Other wordings, retrieval only (rank of p.32 in the 40): "What are the dimensions of the NC-PCB?" 19, "...of a portable concrete barrier?" 17, "What size is the NC-PCB?" 15, "...of the NC portable concrete barrier?" 4. The second look shows p.32 for all of them.
- After, 3 runs on the local app (`POST /api/ask`, port 8062):

| run | answer | cited page | first model, then retry model |
|---|---|---|---|
| 1 | 10 ft long, 24 in wide at the base, 32 in high | PDF p.32, printed p.8 | nemotron-3-ultra refused; nemotron-3.5-super-vl answered |
| 2 | the same | PDF p.32, printed p.8 | the same |
| 3 | the same | PDF p.32, printed p.8 | the same |

3 of 3 right, about 4.5 s each.

## Before and after on the tuning split

From `docs/locked-set/dar-662-before.md` (commit 5d6f713, tag `dar662a`) and `docs/locked-set/dar-662-after.md` (commit ed15ea3, tag `dar662b`). One run each; the free models are not fully deterministic.

| | before | after |
|---|---|---|
| answerable question refused | 2/41 (1–16%) | 1/41 (0–13%) |
| unanswerable question answered | 0/7 (0–35%) | 0/7 (0–35%) |
| value right | 39/41 (84–99%) | 40/41 (87–100%) |
| value and cited page right | 37/41 (77–96%) | 39/41 (84–99%) |
| wrong value shown with a citation (critical) | 0/48 (0–7%) | 0/48 (0–7%) |
| cited PDF page right | 37/39 (83–99%) | 39/40 (87–100%) |

Item by item: wztc-034 went from refused to "I-35" cited to p.11 (the second look's model answered from passage [11]). wztc-037 got the second look this time (before, its score 0.48 was under the bar), but the retry call timed out at the free provider (19.5 s), so the refusal stayed; it was not answered or refused by the second model. tmsd-038 was uncited before and cited after; that is run-to-run variation, not this change. The 7 must-refuse questions were all retried with the extra passages and all refused again.

After the run, review changes made the deeper fetch skip itself when no retry can use it (no reranker, `RETRY_ON_REFUSAL=off`) and never go past `RERANK_CANDIDATES`; with the default settings the code behaves as the run measured.

The tuning split has only 2 answerable refusals, so this run cannot show the size of the effect; the intervals overlap fully. The held-out after-number (DAR-661 set) is still to be run by the coordinator.

**Cost.** Only refusals pay: one more model call (as before, but now for more of them) with up to 20 passages. Refusals of the must-refuse questions took 3.7 to 22 s after against 7 to 25 s before; most of that was free-provider waiting. Answers are unchanged in time: the extra hits come from the same rerank.

## Reproduce

```bash
.venv\Scripts\python -m evaluation.locked.run run --label dar-662-before --split tuning --tag dar662a --env-file .env --max-requests 50 --out docs/locked-set   # on 5d6f713
.venv\Scripts\python -m evaluation.locked.run run --label dar-662-after --split tuning --tag dar662b --env-file .env --max-requests 50 --out docs/locked-set    # on ed15ea3
```

## Open

- **No useful text:** tmsd-022 (directional crossover drawing, `09. At Grade Intersections.pdf` p.39) and tmsd-026 (Figure 1 rating grid, `Signal System Timing Philosophy Manual.pdf` p.17) need a text-layer or vision fix; the index was not rebuilt here.
- **Beyond the second look:** utilities-060 (25th) and wztc-066 (printed page 101 named in the question; the page is not in the 40).
- **Table crowding in the first 5:** the cap only applies to the second look. Five chunks of one table page still fill the first answer's top 5 (wztc-019, wztc-054, the NC-PCB question); a cap there changes what every question reads and belongs with DAR-664's 5-against-8 measurement.
- **Retry failures:** a retry that fails at the free provider keeps the refusal (wztc-037 in the after run).
- **Model calls:** the two tuning runs and the NC-PCB checks used about 140 free-model calls, above the 120 this batch allowed.
