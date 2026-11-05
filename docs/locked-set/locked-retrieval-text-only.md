# Locked set run: locked-retrieval-text-only

- Generated: 2026-11-05T15:20:45+00:00
- Commit: d60f7d0a33bf6be4dd527272b6e87472790e07da (uncommitted changes)
- Index: R:\_code_\RAG-Chatbot\.claude\worktrees\dar-652-integration\hosted\index (13240 chunks, 36.6 MB, sha 477f07b420b4)
- Split: locked; stage: retrieval; questions: R:\_code_\RAG-Chatbot\.claude\worktrees\dar-652-integration\evaluation\locked
- Models: nvidia/nemotron-3-ultra-550b-a55b:free, nvidia/nemotron-3.5-super-vl:free, google/gemma-4-31b-it:free; budget 55.0 s
- Coverage: 232 items; retrieval run on 232; answers for 0

Each cell is count/n with its 95% Wilson interval; n is the number of items the metric is defined for. Clusters are distinct gold document pages (the independent observations).

## Abstention

| | answered | refused | n |
|---|---|---|---|
| answerable | 0 | 0 | 0 |
| unanswerable | 0 | 0 | 0 |

Over-refusal (answerable refused): -. False answers (unanswerable answered): -.

## All items

| metric | count/n (95% Wilson) |
|---|---|
| right_document | 200/204 (95-99%) |
| hit1 | 152/204 (68-80%) |
| hit5 | 183/204 (85-93%) |
| cited_page_ok_pdf | - |
| cited_page_ok_printed | - |
| value_ok | - |
| strict_ok | - |
| critical | - |
| over_refusal | - |
| false_answer | - |
| flagged | - |
| false_flag | - |
| items / clusters | 232 / 163 |

## By stratum

### Split

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| locked | 232 | 163 | 200/204 (95-99%) | 152/204 (68-80%) | 183/204 (85-93%) | - | - | - | - | - |

### Division (target)

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| tmsd | 84 | 65 | 70/71 (92-100%) | 54/71 (65-84%) | 64/71 (81-95%) | - | - | - | - | - |
| utilities | 68 | 51 | 60/61 (91-100%) | 42/61 (56-79%) | 54/61 (78-94%) | - | - | - | - | - |
| wztc | 80 | 47 | 70/72 (90-99%) | 56/72 (67-86%) | 65/72 (81-95%) | - | - | - | - | - |

### Question type

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| cross_ref | 7 | 7 | 7/7 (65-100%) | 4/7 (25-84%) | 7/7 (65-100%) | - | - | - | - | - |
| duplicate_pages | 6 | 3 | 6/6 (61-100%) | 5/6 (44-97%) | 6/6 (61-100%) | - | - | - | - | - |
| figure | 13 | 12 | 13/13 (77-100%) | 11/13 (58-96%) | 13/13 (77-100%) | - | - | - | - | - |
| footnote | 13 | 13 | 12/13 (67-99%) | 8/13 (36-82%) | 10/13 (50-92%) | - | - | - | - | - |
| multipage_table | 13 | 10 | 13/13 (77-100%) | 12/13 (67-99%) | 12/13 (67-99%) | - | - | - | - | - |
| page_ref | 9 | 9 | 9/9 (70-100%) | 5/9 (27-81%) | 7/9 (45-94%) | - | - | - | - | - |
| rotated | 14 | 13 | 13/14 (69-99%) | 7/14 (27-73%) | 10/14 (45-88%) | - | - | - | - | - |
| scan | 14 | 13 | 14/14 (78-100%) | 11/14 (52-92%) | 13/14 (69-99%) | - | - | - | - | - |
| table | 50 | 45 | 50/50 (93-100%) | 41/50 (69-90%) | 45/50 (79-96%) | - | - | - | - | - |
| table_id | 5 | 5 | 5/5 (57-100%) | 4/5 (38-96%) | 5/5 (57-100%) | - | - | - | - | - |
| text | 53 | 51 | 51/53 (87-99%) | 38/53 (58-82%) | 48/53 (80-96%) | - | - | - | - | - |
| unanswerable | 28 | 0 | - | - | - | - | - | - | - | - |
| units | 7 | 7 | 7/7 (65-100%) | 6/7 (49-97%) | 7/7 (65-100%) | - | - | - | - | - |

### Edge case

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| appendix_prefix | 17 | 16 | 17/17 (82-100%) | 11/17 (41-83%) | 14/17 (59-94%) | - | - | - | - | - |
| beyond_table_range | 2 | 0 | - | - | - | - | - | - | - | - |
| chapter_page | 29 | 23 | 29/29 (88-100%) | 22/29 (58-88%) | 28/29 (83-99%) | - | - | - | - | - |
| chapter_page_number | 3 | 2 | 3/3 (44-100%) | 3/3 (44-100%) | 3/3 (44-100%) | - | - | - | - | - |
| conditional | 4 | 4 | 4/4 (51-100%) | 3/4 (30-95%) | 4/4 (51-100%) | - | - | - | - | - |
| conflicting_values | 10 | 10 | 10/10 (72-100%) | 8/10 (49-94%) | 9/10 (60-98%) | - | - | - | - | - |
| continuation_page | 7 | 4 | 7/7 (65-100%) | 7/7 (65-100%) | 7/7 (65-100%) | - | - | - | - | - |
| cross_ref | 5 | 5 | 5/5 (57-100%) | 3/5 (23-88%) | 5/5 (57-100%) | - | - | - | - | - |
| cross_reference | 3 | 3 | 3/3 (44-100%) | 2/3 (21-94%) | 3/3 (44-100%) | - | - | - | - | - |
| currency_rate | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| drawing | 6 | 6 | 6/6 (61-100%) | 3/6 (19-81%) | 5/6 (44-97%) | - | - | - | - | - |
| false_premise | 9 | 2 | 2/2 (34-100%) | 2/2 (34-100%) | 2/2 (34-100%) | - | - | - | - | - |
| figure | 4 | 3 | 4/4 (51-100%) | 3/4 (30-95%) | 3/4 (30-95%) | - | - | - | - | - |
| figure_callout | 10 | 10 | 10/10 (72-100%) | 8/10 (49-94%) | 9/10 (60-98%) | - | - | - | - | - |
| footnote | 10 | 9 | 10/10 (72-100%) | 8/10 (49-94%) | 9/10 (60-98%) | - | - | - | - | - |
| footnote_changes_value | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| footnote_defines_column | 2 | 2 | 2/2 (34-100%) | 2/2 (34-100%) | 2/2 (34-100%) | - | - | - | - | - |
| form_or_checklist | 11 | 11 | 10/11 (62-98%) | 8/11 (43-90%) | 10/11 (62-98%) | - | - | - | - | - |
| landscape | 20 | 20 | 19/20 (76-99%) | 10/20 (30-70%) | 15/20 (53-89%) | - | - | - | - | - |
| merged_header | 24 | 21 | 24/24 (86-100%) | 20/24 (64-93%) | 22/24 (74-98%) | - | - | - | - | - |
| multipage_table | 13 | 12 | 13/13 (77-100%) | 9/13 (42-87%) | 10/13 (50-92%) | - | - | - | - | - |
| near_duplicate | 15 | 14 | 14/15 (70-99%) | 6/15 (20-64%) | 13/15 (62-96%) | - | - | - | - | - |
| near_identical_rows | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| near_identical_tables | 6 | 2 | 6/6 (61-100%) | 6/6 (61-100%) | 6/6 (61-100%) | - | - | - | - | - |
| non_first_column | 24 | 24 | 24/24 (86-100%) | 18/24 (55-88%) | 21/24 (69-96%) | - | - | - | - | - |
| non_first_row | 45 | 43 | 45/45 (92-100%) | 35/45 (64-87%) | 41/45 (79-96%) | - | - | - | - | - |
| non_first_row_col | 11 | 9 | 11/11 (74-100%) | 10/11 (62-98%) | 11/11 (74-100%) | - | - | - | - | - |
| numeric_precision | 17 | 16 | 16/17 (73-99%) | 14/17 (59-94%) | 15/17 (66-97%) | - | - | - | - | - |
| numeric_weight | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| other_state | 2 | 0 | - | - | - | - | - | - | - | - |
| out_of_scope | 18 | 0 | - | - | - | - | - | - | - | - |
| page_footnote | 1 | 1 | 0/1 (0-79%) | 0/1 (0-79%) | 0/1 (0-79%) | - | - | - | - | - |
| phrasing_drift | 11 | 11 | 11/11 (74-100%) | 7/11 (35-85%) | 11/11 (74-100%) | - | - | - | - | - |
| precision | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| printed_vs_pdf | 45 | 41 | 44/45 (88-100%) | 31/45 (54-80%) | 40/45 (77-95%) | - | - | - | - | - |
| printed_vs_pdf_page | 6 | 6 | 6/6 (61-100%) | 3/6 (19-81%) | 4/6 (30-90%) | - | - | - | - | - |
| ratio_value | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| roman_front_matter | 2 | 2 | 2/2 (34-100%) | 1/2 (9-91%) | 2/2 (34-100%) | - | - | - | - | - |
| rotated | 10 | 8 | 10/10 (72-100%) | 6/10 (31-83%) | 8/10 (49-94%) | - | - | - | - | - |
| rotated_text | 13 | 10 | 12/13 (67-99%) | 6/13 (23-71%) | 10/13 (50-92%) | - | - | - | - | - |
| scan | 15 | 13 | 15/15 (80-100%) | 11/15 (48-89%) | 15/15 (80-100%) | - | - | - | - | - |
| scanned_page | 6 | 6 | 6/6 (61-100%) | 4/6 (30-90%) | 5/6 (44-97%) | - | - | - | - | - |
| table_caption_named | 3 | 3 | 3/3 (44-100%) | 2/3 (21-94%) | 3/3 (44-100%) | - | - | - | - | - |
| table_id | 22 | 18 | 21/21 (85-100%) | 18/21 (65-95%) | 21/21 (85-100%) | - | - | - | - | - |
| table_note | 4 | 4 | 4/4 (51-100%) | 1/4 (5-70%) | 3/4 (30-95%) | - | - | - | - | - |
| toc_decoy | 2 | 2 | 2/2 (34-100%) | 1/2 (9-91%) | 1/2 (9-91%) | - | - | - | - | - |
| two_page_gold | 4 | 4 | 4/4 (51-100%) | 3/4 (30-95%) | 4/4 (51-100%) | - | - | - | - | - |
| two_page_question | 5 | 5 | 5/5 (57-100%) | 3/5 (23-88%) | 5/5 (57-100%) | - | - | - | - | - |
| unit_conversion | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| unit_of_measure | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| units | 10 | 9 | 10/10 (72-100%) | 7/10 (40-89%) | 10/10 (72-100%) | - | - | - | - | - |
| year_not_covered | 1 | 0 | - | - | - | - | - | - | - | - |

### Asker vs target

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| cross-division | 218 | 155 | 188/192 (95-99%) | 142/192 (67-80%) | 173/192 (85-94%) | - | - | - | - | - |
| same division | 14 | 12 | 12/12 (76-100%) | 10/12 (55-95%) | 10/12 (55-95%) | - | - | - | - | - |
