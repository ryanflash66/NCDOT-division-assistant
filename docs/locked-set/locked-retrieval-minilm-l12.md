# Locked set run: locked-retrieval-minilm-l12

- Generated: 2026-11-05T15:22:22+00:00
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
| hit1 | 147/204 (66-78%) |
| hit5 | 180/204 (83-92%) |
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
| locked | 232 | 163 | 200/204 (95-99%) | 147/204 (66-78%) | 180/204 (83-92%) | - | - | - | - | - |

### Division (target)

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| tmsd | 84 | 65 | 70/71 (92-100%) | 53/71 (63-83%) | 62/71 (78-93%) | - | - | - | - | - |
| utilities | 68 | 51 | 60/61 (91-100%) | 38/61 (50-73%) | 52/61 (74-92%) | - | - | - | - | - |
| wztc | 80 | 47 | 70/72 (90-99%) | 56/72 (67-86%) | 66/72 (83-96%) | - | - | - | - | - |

### Question type

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| cross_ref | 7 | 7 | 7/7 (65-100%) | 4/7 (25-84%) | 7/7 (65-100%) | - | - | - | - | - |
| duplicate_pages | 6 | 3 | 6/6 (61-100%) | 5/6 (44-97%) | 6/6 (61-100%) | - | - | - | - | - |
| figure | 13 | 12 | 13/13 (77-100%) | 11/13 (58-96%) | 13/13 (77-100%) | - | - | - | - | - |
| footnote | 13 | 13 | 13/13 (77-100%) | 8/13 (36-82%) | 12/13 (67-99%) | - | - | - | - | - |
| multipage_table | 13 | 10 | 13/13 (77-100%) | 11/13 (58-96%) | 12/13 (67-99%) | - | - | - | - | - |
| page_ref | 9 | 9 | 9/9 (70-100%) | 6/9 (35-88%) | 7/9 (45-94%) | - | - | - | - | - |
| rotated | 14 | 13 | 13/14 (69-99%) | 4/14 (12-55%) | 8/14 (33-79%) | - | - | - | - | - |
| scan | 14 | 13 | 13/14 (69-99%) | 11/14 (52-92%) | 13/14 (69-99%) | - | - | - | - | - |
| table | 50 | 45 | 50/50 (93-100%) | 38/50 (63-86%) | 45/50 (79-96%) | - | - | - | - | - |
| table_id | 5 | 5 | 5/5 (57-100%) | 5/5 (57-100%) | 5/5 (57-100%) | - | - | - | - | - |
| text | 53 | 51 | 51/53 (87-99%) | 37/53 (56-80%) | 45/53 (73-92%) | - | - | - | - | - |
| unanswerable | 28 | 0 | - | - | - | - | - | - | - | - |
| units | 7 | 7 | 7/7 (65-100%) | 7/7 (65-100%) | 7/7 (65-100%) | - | - | - | - | - |

### Edge case

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| appendix_prefix | 17 | 16 | 17/17 (82-100%) | 8/17 (26-69%) | 14/17 (59-94%) | - | - | - | - | - |
| beyond_table_range | 2 | 0 | - | - | - | - | - | - | - | - |
| chapter_page | 29 | 23 | 29/29 (88-100%) | 24/29 (65-92%) | 26/29 (74-96%) | - | - | - | - | - |
| chapter_page_number | 3 | 2 | 3/3 (44-100%) | 3/3 (44-100%) | 3/3 (44-100%) | - | - | - | - | - |
| conditional | 4 | 4 | 4/4 (51-100%) | 3/4 (30-95%) | 4/4 (51-100%) | - | - | - | - | - |
| conflicting_values | 10 | 10 | 10/10 (72-100%) | 6/10 (31-83%) | 9/10 (60-98%) | - | - | - | - | - |
| continuation_page | 7 | 4 | 7/7 (65-100%) | 7/7 (65-100%) | 7/7 (65-100%) | - | - | - | - | - |
| cross_ref | 5 | 5 | 5/5 (57-100%) | 3/5 (23-88%) | 5/5 (57-100%) | - | - | - | - | - |
| cross_reference | 3 | 3 | 3/3 (44-100%) | 2/3 (21-94%) | 3/3 (44-100%) | - | - | - | - | - |
| currency_rate | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| drawing | 6 | 6 | 6/6 (61-100%) | 3/6 (19-81%) | 5/6 (44-97%) | - | - | - | - | - |
| false_premise | 9 | 2 | 2/2 (34-100%) | 2/2 (34-100%) | 2/2 (34-100%) | - | - | - | - | - |
| figure | 4 | 3 | 4/4 (51-100%) | 3/4 (30-95%) | 3/4 (30-95%) | - | - | - | - | - |
| figure_callout | 10 | 10 | 10/10 (72-100%) | 8/10 (49-94%) | 9/10 (60-98%) | - | - | - | - | - |
| footnote | 10 | 9 | 10/10 (72-100%) | 8/10 (49-94%) | 8/10 (49-94%) | - | - | - | - | - |
| footnote_changes_value | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| footnote_defines_column | 2 | 2 | 2/2 (34-100%) | 1/2 (9-91%) | 2/2 (34-100%) | - | - | - | - | - |
| form_or_checklist | 11 | 11 | 10/11 (62-98%) | 6/11 (28-79%) | 10/11 (62-98%) | - | - | - | - | - |
| landscape | 20 | 20 | 19/20 (76-99%) | 8/20 (22-61%) | 14/20 (48-85%) | - | - | - | - | - |
| merged_header | 24 | 21 | 24/24 (86-100%) | 17/24 (51-85%) | 21/24 (69-96%) | - | - | - | - | - |
| multipage_table | 13 | 12 | 13/13 (77-100%) | 6/13 (23-71%) | 11/13 (58-96%) | - | - | - | - | - |
| near_duplicate | 15 | 14 | 14/15 (70-99%) | 6/15 (20-64%) | 11/15 (48-89%) | - | - | - | - | - |
| near_identical_rows | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| near_identical_tables | 6 | 2 | 6/6 (61-100%) | 6/6 (61-100%) | 6/6 (61-100%) | - | - | - | - | - |
| non_first_column | 24 | 24 | 24/24 (86-100%) | 16/24 (47-82%) | 19/24 (60-91%) | - | - | - | - | - |
| non_first_row | 45 | 43 | 45/45 (92-100%) | 33/45 (59-84%) | 39/45 (74-94%) | - | - | - | - | - |
| non_first_row_col | 11 | 9 | 11/11 (74-100%) | 10/11 (62-98%) | 11/11 (74-100%) | - | - | - | - | - |
| numeric_precision | 17 | 16 | 16/17 (73-99%) | 14/17 (59-94%) | 15/17 (66-97%) | - | - | - | - | - |
| numeric_weight | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| other_state | 2 | 0 | - | - | - | - | - | - | - | - |
| out_of_scope | 18 | 0 | - | - | - | - | - | - | - | - |
| page_footnote | 1 | 1 | 1/1 (21-100%) | 0/1 (0-79%) | 1/1 (21-100%) | - | - | - | - | - |
| phrasing_drift | 11 | 11 | 11/11 (74-100%) | 8/11 (43-90%) | 10/11 (62-98%) | - | - | - | - | - |
| precision | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| printed_vs_pdf | 45 | 41 | 44/45 (88-100%) | 31/45 (54-80%) | 38/45 (71-92%) | - | - | - | - | - |
| printed_vs_pdf_page | 6 | 6 | 6/6 (61-100%) | 3/6 (19-81%) | 4/6 (30-90%) | - | - | - | - | - |
| ratio_value | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| roman_front_matter | 2 | 2 | 2/2 (34-100%) | 0/2 (0-66%) | 0/2 (0-66%) | - | - | - | - | - |
| rotated | 10 | 8 | 10/10 (72-100%) | 4/10 (17-69%) | 7/10 (40-89%) | - | - | - | - | - |
| rotated_text | 13 | 10 | 12/13 (67-99%) | 6/13 (23-71%) | 10/13 (50-92%) | - | - | - | - | - |
| scan | 15 | 13 | 15/15 (80-100%) | 11/15 (48-89%) | 15/15 (80-100%) | - | - | - | - | - |
| scanned_page | 6 | 6 | 5/6 (44-97%) | 4/6 (30-90%) | 5/6 (44-97%) | - | - | - | - | - |
| table_caption_named | 3 | 3 | 3/3 (44-100%) | 3/3 (44-100%) | 3/3 (44-100%) | - | - | - | - | - |
| table_id | 22 | 18 | 21/21 (85-100%) | 18/21 (65-95%) | 19/21 (71-97%) | - | - | - | - | - |
| table_note | 4 | 4 | 4/4 (51-100%) | 2/4 (15-85%) | 4/4 (51-100%) | - | - | - | - | - |
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
| cross-division | 218 | 155 | 188/192 (95-99%) | 138/192 (65-78%) | 170/192 (83-92%) | - | - | - | - | - |
| same division | 14 | 12 | 12/12 (76-100%) | 9/12 (47-91%) | 10/12 (55-95%) | - | - | - | - | - |
