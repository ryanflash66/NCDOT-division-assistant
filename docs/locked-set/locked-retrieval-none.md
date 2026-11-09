# Locked set run: locked-retrieval-none

- Generated: 2026-11-05T15:19:27+00:00
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
| right_document | 201/204 (96-99%) |
| hit1 | 136/204 (60-73%) |
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
| locked | 232 | 163 | 201/204 (96-99%) | 136/204 (60-73%) | 183/204 (85-93%) | - | - | - | - | - |

### Division (target)

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| tmsd | 84 | 65 | 69/71 (90-99%) | 45/71 (52-74%) | 62/71 (78-93%) | - | - | - | - | - |
| utilities | 68 | 51 | 60/61 (91-100%) | 42/61 (56-79%) | 56/61 (82-96%) | - | - | - | - | - |
| wztc | 80 | 47 | 72/72 (95-100%) | 49/72 (57-78%) | 65/72 (81-95%) | - | - | - | - | - |

### Question type

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| cross_ref | 7 | 7 | 7/7 (65-100%) | 6/7 (49-97%) | 7/7 (65-100%) | - | - | - | - | - |
| duplicate_pages | 6 | 3 | 6/6 (61-100%) | 5/6 (44-97%) | 6/6 (61-100%) | - | - | - | - | - |
| figure | 13 | 12 | 13/13 (77-100%) | 6/13 (23-71%) | 11/13 (58-96%) | - | - | - | - | - |
| footnote | 13 | 13 | 13/13 (77-100%) | 4/13 (13-58%) | 12/13 (67-99%) | - | - | - | - | - |
| multipage_table | 13 | 10 | 13/13 (77-100%) | 11/13 (58-96%) | 11/13 (58-96%) | - | - | - | - | - |
| page_ref | 9 | 9 | 9/9 (70-100%) | 5/9 (27-81%) | 7/9 (45-94%) | - | - | - | - | - |
| rotated | 14 | 13 | 14/14 (78-100%) | 7/14 (27-73%) | 11/14 (52-92%) | - | - | - | - | - |
| scan | 14 | 13 | 14/14 (78-100%) | 10/14 (45-88%) | 13/14 (69-99%) | - | - | - | - | - |
| table | 50 | 45 | 50/50 (93-100%) | 42/50 (71-92%) | 46/50 (81-97%) | - | - | - | - | - |
| table_id | 5 | 5 | 5/5 (57-100%) | 4/5 (38-96%) | 4/5 (38-96%) | - | - | - | - | - |
| text | 53 | 51 | 50/53 (85-98%) | 30/53 (43-69%) | 48/53 (80-96%) | - | - | - | - | - |
| unanswerable | 28 | 0 | - | - | - | - | - | - | - | - |
| units | 7 | 7 | 7/7 (65-100%) | 6/7 (49-97%) | 7/7 (65-100%) | - | - | - | - | - |

### Edge case

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| appendix_prefix | 17 | 16 | 17/17 (82-100%) | 12/17 (47-87%) | 14/17 (59-94%) | - | - | - | - | - |
| beyond_table_range | 2 | 0 | - | - | - | - | - | - | - | - |
| chapter_page | 29 | 23 | 28/29 (83-99%) | 21/29 (54-85%) | 28/29 (83-99%) | - | - | - | - | - |
| chapter_page_number | 3 | 2 | 3/3 (44-100%) | 3/3 (44-100%) | 3/3 (44-100%) | - | - | - | - | - |
| conditional | 4 | 4 | 4/4 (51-100%) | 3/4 (30-95%) | 4/4 (51-100%) | - | - | - | - | - |
| conflicting_values | 10 | 10 | 10/10 (72-100%) | 7/10 (40-89%) | 10/10 (72-100%) | - | - | - | - | - |
| continuation_page | 7 | 4 | 7/7 (65-100%) | 7/7 (65-100%) | 7/7 (65-100%) | - | - | - | - | - |
| cross_ref | 5 | 5 | 5/5 (57-100%) | 5/5 (57-100%) | 5/5 (57-100%) | - | - | - | - | - |
| cross_reference | 3 | 3 | 3/3 (44-100%) | 2/3 (21-94%) | 3/3 (44-100%) | - | - | - | - | - |
| currency_rate | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| drawing | 6 | 6 | 6/6 (61-100%) | 2/6 (10-70%) | 4/6 (30-90%) | - | - | - | - | - |
| false_premise | 9 | 2 | 2/2 (34-100%) | 2/2 (34-100%) | 2/2 (34-100%) | - | - | - | - | - |
| figure | 4 | 3 | 4/4 (51-100%) | 3/4 (30-95%) | 3/4 (30-95%) | - | - | - | - | - |
| figure_callout | 10 | 10 | 10/10 (72-100%) | 3/10 (11-60%) | 7/10 (40-89%) | - | - | - | - | - |
| footnote | 10 | 9 | 10/10 (72-100%) | 6/10 (31-83%) | 10/10 (72-100%) | - | - | - | - | - |
| footnote_changes_value | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| footnote_defines_column | 2 | 2 | 2/2 (34-100%) | 1/2 (9-91%) | 1/2 (9-91%) | - | - | - | - | - |
| form_or_checklist | 11 | 11 | 11/11 (74-100%) | 8/11 (43-90%) | 10/11 (62-98%) | - | - | - | - | - |
| landscape | 20 | 20 | 20/20 (84-100%) | 9/20 (26-66%) | 15/20 (53-89%) | - | - | - | - | - |
| merged_header | 24 | 21 | 24/24 (86-100%) | 20/24 (64-93%) | 23/24 (80-99%) | - | - | - | - | - |
| multipage_table | 13 | 12 | 13/13 (77-100%) | 8/13 (36-82%) | 9/13 (42-87%) | - | - | - | - | - |
| near_duplicate | 15 | 14 | 14/15 (70-99%) | 6/15 (20-64%) | 13/15 (62-96%) | - | - | - | - | - |
| near_identical_rows | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| near_identical_tables | 6 | 2 | 6/6 (61-100%) | 6/6 (61-100%) | 6/6 (61-100%) | - | - | - | - | - |
| non_first_column | 24 | 24 | 24/24 (86-100%) | 19/24 (60-91%) | 22/24 (74-98%) | - | - | - | - | - |
| non_first_row | 45 | 43 | 45/45 (92-100%) | 35/45 (64-87%) | 41/45 (79-96%) | - | - | - | - | - |
| non_first_row_col | 11 | 9 | 11/11 (74-100%) | 10/11 (62-98%) | 11/11 (74-100%) | - | - | - | - | - |
| numeric_precision | 17 | 16 | 15/17 (66-97%) | 12/17 (47-87%) | 14/17 (59-94%) | - | - | - | - | - |
| numeric_weight | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| other_state | 2 | 0 | - | - | - | - | - | - | - | - |
| out_of_scope | 18 | 0 | - | - | - | - | - | - | - | - |
| page_footnote | 1 | 1 | 1/1 (21-100%) | 0/1 (0-79%) | 1/1 (21-100%) | - | - | - | - | - |
| phrasing_drift | 11 | 11 | 10/11 (62-98%) | 5/11 (21-72%) | 10/11 (62-98%) | - | - | - | - | - |
| precision | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| printed_vs_pdf | 45 | 41 | 45/45 (92-100%) | 30/45 (52-79%) | 43/45 (85-99%) | - | - | - | - | - |
| printed_vs_pdf_page | 6 | 6 | 6/6 (61-100%) | 3/6 (19-81%) | 4/6 (30-90%) | - | - | - | - | - |
| ratio_value | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| roman_front_matter | 2 | 2 | 2/2 (34-100%) | 0/2 (0-66%) | 2/2 (34-100%) | - | - | - | - | - |
| rotated | 10 | 8 | 10/10 (72-100%) | 5/10 (24-76%) | 8/10 (49-94%) | - | - | - | - | - |
| rotated_text | 13 | 10 | 13/13 (77-100%) | 5/13 (18-64%) | 11/13 (58-96%) | - | - | - | - | - |
| scan | 15 | 13 | 15/15 (80-100%) | 11/15 (48-89%) | 15/15 (80-100%) | - | - | - | - | - |
| scanned_page | 6 | 6 | 6/6 (61-100%) | 4/6 (30-90%) | 5/6 (44-97%) | - | - | - | - | - |
| table_caption_named | 3 | 3 | 3/3 (44-100%) | 2/3 (21-94%) | 2/3 (21-94%) | - | - | - | - | - |
| table_id | 22 | 18 | 21/21 (85-100%) | 18/21 (65-95%) | 21/21 (85-100%) | - | - | - | - | - |
| table_note | 4 | 4 | 4/4 (51-100%) | 0/4 (0-49%) | 4/4 (51-100%) | - | - | - | - | - |
| toc_decoy | 2 | 2 | 2/2 (34-100%) | 0/2 (0-66%) | 2/2 (34-100%) | - | - | - | - | - |
| two_page_gold | 4 | 4 | 4/4 (51-100%) | 3/4 (30-95%) | 4/4 (51-100%) | - | - | - | - | - |
| two_page_question | 5 | 5 | 5/5 (57-100%) | 5/5 (57-100%) | 5/5 (57-100%) | - | - | - | - | - |
| unit_conversion | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| unit_of_measure | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| units | 10 | 9 | 10/10 (72-100%) | 7/10 (40-89%) | 10/10 (72-100%) | - | - | - | - | - |
| year_not_covered | 1 | 0 | - | - | - | - | - | - | - | - |

### Asker vs target

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| cross-division | 218 | 155 | 189/192 (96-99%) | 128/192 (60-73%) | 172/192 (84-93%) | - | - | - | - | - |
| same division | 14 | 12 | 12/12 (76-100%) | 8/12 (39-86%) | 11/12 (65-99%) | - | - | - | - | - |
