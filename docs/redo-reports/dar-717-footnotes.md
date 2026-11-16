# DAR-717: footnote questions answered from the table instead of its note

**What changed** (decision log, DAR-717 entry). The note lines printed under a table now go into that table's chunks as a "Notes:" block at the end of every piece of the table; a note the PDF reader dropped is put back from the page's text layer; chunks that carry notes are tagged `notes` and found by "note" and "footnote" in the keyword field; and a question that names a note or footnote gets one more prompt rule: answer from the note and quote it.

## Why: where the note text was

Footnote questions were the only type that got worse in the redo: value right 10/13 → 8/13 on the locked split (`docs/redo-methods.md` section 3.2). The three locked items below were read to find the cause; they are not used as a measure. Chunk numbers are positions in `hosted/index/chunks.json` on main before this change (5d6f713, 13,240 chunks). "Reached the model" is what `Answerer.retrieve` passes to the prompt for the item's question on that index (no model call).

| item | page | where the note was | reached the model? | answer after the redo |
|---|---|---|---|---|
| wztc-052, Table 24 conditions | FHWA road user cost report (fhwahop12005.pdf) p.50 | "Note: Reported for work zones with active work and temporary lane closure." is under Table 24, but the splitter takes up to two short lines above a table as its caption, so the note became the caption of **Table 25** (chunks #4835 and #4836). Table 24's own chunk #4834 has no note. | No. Passages were #4833+#4834 (Table 24, no note) and #4838+#4839. | "temporary lane closure on freeways": Table 24's caption, without the note's "active work" |
| wztc-053, Table 12 CPI | same report, p.41 | "Source: … Original CPI: 142.8 (year 1996) Current year CPI: 193.396 (year 2010)" is under Table 12, but it began the next prose chunk (#4772, with section 2.3.2.2), apart from the table chunks #4760–#4771. | No. Passages were the Table 12 chunks #4761+#4762, #4766+#4767, #4770+#4771. | refused |
| wztc-055, note to Table 1080-1 | Standard Specifications p.580 | Dropped. The table is printed sideways; pymupdf4llm's Markdown has the grid (chunk #1978) but not "A. Use a 5% acetic acid solution with a pH 4 + 2 to determine solubility.", which the page's text layer has. No chunk holds it. | No (not in the index). Passage #1978+#1979 was cited. | "ASTM D1135 & D3256", the test method in the table's "Acid Soluble Pigments" column |

Also checked: the next page, p.581 (Table 1080-2, locked item wztc-054), keeps its note "A. Or approved equivalent", but glued into the table's first header cell (#1979). On the tuning page UAM p.101 (utilities-002) the notes a, b and c under Table 3-1 were a prose chunk of their own (#5598) after the table chunks #5595–#5597; that question was answered right before because the passage merge joins consecutive chunks, so #5598 rode along with the table.

None of this is caught by the number check (DAR-659): in each wrong answer the wrong text is printed on the cited page.

So the cause is in the index, not only in the prompt: in two of the three cases the note never reached the model, and in the third it was not in the index at all.

## The fix

- `rag/table_notes.py` (new): what a note line looks like ("Note:", "Notes:", "Source:", a letter marker such as "a …", "A. …", "b) …", a superscript marker, "* …", "† …"; numbered lines only under a "Notes:" line), the "Notes:" block, and the recovery of a note line that the Markdown left out.
- `rag/tables.py`: the note lines right under a table are taken before the next table's caption is looked for, and end every piece of the table as a "Notes:" block. Notes longer than a third of a chunk (170 of 512 tokens) are left as prose, so a long list of notes does not crowd out the rows.
- `rag/table_merge.py`: when a table runs over a page break, the notes under its continued part move with its rows (the FHWA Table 12 case: rows on pp.40–41, "Source:" line on p.41).
- `rag/loader.py`: on a page with a table, a text-layer line that reads as a note and whose words are nowhere in the Markdown is put back under the page's last table.
- `prototype/ingest.py`: a chunk with a notes block gets `"notes": true`. `hosted/divrag/index_file.py` adds "table notes footnotes" to such a chunk's caption/ID field (DAR-657), so "note" and "footnote" in a question count there.
- `hosted/divrag/answer.py`: `NOTE_RULE`, added as rule 8 (or 9 after the page rule) only when the question says "footnote" or "superscript", or uses "note" as a noun ("the note to Table 1080-1", "the notes for Figure 6P-2", "correction note in"). "Does the manual note a minimum depth" does not get it. Every other question gets exactly the prompt it got before.

A note line is one of those shapes, right under the table's last row (blank lines between are skipped), at most 8 lines and 600 characters each. A lettered line ("A. …", "a …", "<sup>b</sup> …") counts only when the table marks a cell with that letter ("Pigments**A**", "Auger<sup>a</sup>"). Without that check the first rebuild took the TMP strategies matrix's next headings ("A. Control Strategies", trans_mgmt_plans.pdf) and the FHWA report's hollow-bullet lists ("o Pickups & vans") as notes. A bare "Note:" line with no note after it is not taken.

## What the index looks like now

Rebuilt with `python -m prototype.ingest --ocr --reuse hosted/index` (chunks still 512 tokens).

| | main (5d6f713) | this branch |
|---|---|---|
| chunks | 13,240 | 13,272 |
| chunk texts added / removed | | 523 / 491, on 101 pages |
| chunks with a notes block (`notes: true`) | 0 | 418, on 100 pages of 18 documents (wztc 175, utilities 53, tmsd 190) |

The four pages above, on the new index, with what `Answerer.retrieve` passes to the model (no model call):

| item | note now | reaches the model? |
|---|---|---|
| wztc-052 (FHWA p.50) | in Table 24's chunk; Table 25's caption no longer has it | yes, passage [1] |
| wztc-053 (FHWA p.41) | in all 6 chunks of the joined Table 12 | yes, passages [2] and [3] |
| wztc-055 (Spec p.580) | put back from the text layer, in the table chunk | yes, passage [3] |
| utilities-002 (UAM p.101) | in all 5 chunks of Table 3-1 | yes, passage [1] |

Two code-review fixes came after this rebuild: ligature glyphs ("ﬁ") are spelled out before a text-layer note is compared with the Markdown, and only chunks with table rows are tagged `notes`. Neither changes this index: none of the 62 PDFs has a ligature glyph in its text layer, and no tagged chunk lacked table rows. So the committed index is what the committed code builds.

Known false positive left in: on trans_mgmt_plans.pdf p.94 the heading "I. Temporary Traffic Control (TTC) Strategies (Continued)" became a note of the strategies matrix (6 chunks), because the column header "Mobility Impact" is split as "**Mobility** **I**". It only repeats a heading.

## Results: tuning split, before and after

Same 48 tuning items, same three free models, `--tag dar717a` / `--tag dar717b`. Files: [`../locked-set/dar-717-before.md`](../locked-set/dar-717-before.md) and [`../locked-set/dar-717-after.md`](../locked-set/dar-717-after.md).

To stay inside the 120-call budget the after run asked the models only for the items whose model input changed. For each item the system and user messages were built on both indexes without a model call; 34 of the 48 were identical, and their before answers were copied into the after run's cache (records marked `carried_from`). The other 14 were asked again: tmsd-093, utilities-001, utilities-002, utilities-063, utilities-072, wztc-009, wztc-016, wztc-034, wztc-037, wztc-057, wztc-058, wztc-062, wztc-076, wztc-088. Retrieval metrics were computed fresh for all 48.

| | before | after |
|---|---|---|
| **footnote** value right | 1/1 (21–100%) | 1/1 (21–100%) |
| **table** value right | 8/8 (68–100%) | 8/8 (68–100%) |
| **table_id** value right | 3/3 (44–100%) | 3/3 (44–100%) |
| table + table_id, value and cited page right | 11/11 (74–100%) | 11/11 (74–100%) |
| all: right document in top 5 | 41/41 (91–100%) | 40/41 (87–100%) |
| all: right page first | 33/41 (66–90%) | 34/41 (69–91%) |
| all: right page in top 5 | 39/41 (84–99%) | 39/41 (84–99%) |
| all: cited PDF page right | 38/39 (87–100%) | 38/39 (87–100%) |
| all: value right | 38/41 (81–97%) | 38/41 (81–97%) |
| all: value and cited page right | 37/41 (77–96%) | 37/41 (77–96%) |
| confident wrong answer | 1/48 (0–11%) | 1/48 (0–11%) |
| answerable refused | 2/41 (1–16%) | 2/41 (1–16%) |
| unanswerable answered | 0/7 (0–35%) | 0/7 (0–35%) |

What moved: wztc-062 (units) now has the right page first. wztc-037 (scan, "share of a traffic cone's weight in its base", gold Chapter_2.pdf p.26) lost its right-document hit: Chapter_2.pdf p.41 (not the gold page) left the top 5 and a second Standard Specifications p.274 chunk took its place; the question was refused before and after. The other changed answers are rewordings of the same value.

The tuning split has one footnote question, so it cannot show the gain; it shows that table questions did not get worse. The only footnote evidence is the three locked items below, which were read to find the cause and are not a measure.

## The three ticket questions on the local app

`POST /api/ask` on port 8017 with this branch's index, target wztc, no history (3 model calls; first model answered each):

| item | answer | cited |
|---|---|---|
| wztc-052 | "reported for work zones with active work and temporary lane closure on freeways" | FHWA-HOP-12-005 p.50 |
| wztc-053 | "193.396" | FHWA-HOP-12-005 pp.40, 41 |
| wztc-055 | "A 5% acetic acid solution with a pH of 4 ± 2" | Standard Specifications p.580 |

All three are right (before: Table 24's caption, a refusal, and the table's test method). Only wztc-055 says "note", so only it got the new prompt rule; the other two were fixed by the index alone.

## Reproduce

```bash
.venv\Scripts\python -m prototype.ingest --ocr --reuse hosted/index
.venv\Scripts\python -m pytest tests/test_table_notes.py tests/test_hosted_table_notes.py
.venv\Scripts\python -m evaluation.locked.run run --label dar-717-after --split tuning --tag dar717b --env-file .env --max-requests 20 --out docs/locked-set
```

The after run needs the 34 carried answers in `evaluation/locked/results/cache.jsonl` to make only 14 calls; without them it asks all 48.

## Not done

- No after-number on held-out questions: the coordinator runs that.
- The locked split was not rerun (D17).
- p.581 (Table 1080-2): its note "A. Or approved equivalent" is still glued into the first header cell by pymupdf4llm; the note text is in the chunk, but not as a "Notes:" block.
- Notes are found only right under a table. A note printed at the foot of the page, after other prose, is not moved.
- The trans_mgmt_plans.pdf p.94 false positive above.
- Found in code review, left open:
  - The notes block is at the end of each table piece. In a full 512-token piece the embedder and reranker, which stop at 512 of their own tokens, may not read it. The model and the keyword search still see it.
  - When the passage merge joins two pieces of one table, the notes block appears twice in that passage.
  - A recovered "Note:" or "Source:" line goes under the page's last table, even if it belonged to an earlier table or a figure. How many of the 418 tagged chunks got their notes this way was not counted.
  - At most 8 note lines are taken; a 9th stays prose. A list of "* " bullets right under a table would be taken as notes.
