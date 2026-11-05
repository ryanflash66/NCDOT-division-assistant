# Locked set run: locked-retrieval-page-sum

- Generated: 2026-11-05T15:25:49+00:00
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
| right_document | 199/204 (94-99%) |
| hit1 | 138/204 (61-74%) |
| hit5 | 178/204 (82-91%) |
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
| locked | 232 | 163 | 199/204 (94-99%) | 138/204 (61-74%) | 178/204 (82-91%) | - | - | - | - | - |

### Division (target)

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| tmsd | 84 | 65 | 70/71 (92-100%) | 48/71 (56-77%) | 64/71 (81-95%) | - | - | - | - | - |
| utilities | 68 | 51 | 60/61 (91-100%) | 39/61 (51-75%) | 51/61 (72-91%) | - | - | - | - | - |
| wztc | 80 | 47 | 69/72 (88-99%) | 51/72 (59-80%) | 63/72 (78-93%) | - | - | - | - | - |

### Question type

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| cross_ref | 7 | 7 | 7/7 (65-100%) | 4/7 (25-84%) | 7/7 (65-100%) | - | - | - | - | - |
| duplicate_pages | 6 | 3 | 6/6 (61-100%) | 5/6 (44-97%) | 6/6 (61-100%) | - | - | - | - | - |
| figure | 13 | 12 | 13/13 (77-100%) | 11/13 (58-96%) | 13/13 (77-100%) | - | - | - | - | - |
| footnote | 13 | 13 | 12/13 (67-99%) | 7/13 (29-77%) | 10/13 (50-92%) | - | - | - | - | - |
| multipage_table | 13 | 10 | 13/13 (77-100%) | 11/13 (58-96%) | 12/13 (67-99%) | - | - | - | - | - |
| page_ref | 9 | 9 | 9/9 (70-100%) | 5/9 (27-81%) | 7/9 (45-94%) | - | - | - | - | - |
| rotated | 14 | 13 | 13/14 (69-99%) | 5/14 (16-61%) | 8/14 (33-79%) | - | - | - | - | - |
| scan | 14 | 13 | 13/14 (69-99%) | 10/14 (45-88%) | 13/14 (69-99%) | - | - | - | - | - |
| table | 50 | 45 | 50/50 (93-100%) | 34/50 (54-79%) | 46/50 (81-97%) | - | - | - | - | - |
| table_id | 5 | 5 | 5/5 (57-100%) | 4/5 (38-96%) | 5/5 (57-100%) | - | - | - | - | - |
| text | 53 | 51 | 51/53 (87-99%) | 35/53 (53-77%) | 44/53 (71-91%) | - | - | - | - | - |
| unanswerable | 28 | 0 | - | - | - | - | - | - | - | - |
| units | 7 | 7 | 7/7 (65-100%) | 7/7 (65-100%) | 7/7 (65-100%) | - | - | - | - | - |

### Edge case

| stratum | items | clusters | right doc | hit@1 | hit@5 | cited PDF page | cited printed page | value | strict | critical |
|---|---|---|---|---|---|---|---|---|---|---|
| appendix_prefix | 17 | 16 | 17/17 (82-100%) | 8/17 (26-69%) | 14/17 (59-94%) | - | - | - | - | - |
| beyond_table_range | 2 | 0 | - | - | - | - | - | - | - | - |
| chapter_page | 29 | 23 | 29/29 (88-100%) | 24/29 (65-92%) | 26/29 (74-96%) | - | - | - | - | - |
| chapter_page_number | 3 | 2 | 3/3 (44-100%) | 2/3 (21-94%) | 3/3 (44-100%) | - | - | - | - | - |
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
| footnote | 10 | 9 | 10/10 (72-100%) | 5/10 (24-76%) | 8/10 (49-94%) | - | - | - | - | - |
| footnote_changes_value | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| footnote_defines_column | 2 | 2 | 2/2 (34-100%) | 2/2 (34-100%) | 2/2 (34-100%) | - | - | - | - | - |
| form_or_checklist | 11 | 11 | 10/11 (62-98%) | 6/11 (28-79%) | 9/11 (52-95%) | - | - | - | - | - |
| landscape | 20 | 20 | 19/20 (76-99%) | 9/20 (26-66%) | 14/20 (48-85%) | - | - | - | - | - |
| merged_header | 24 | 21 | 24/24 (86-100%) | 18/24 (55-88%) | 24/24 (86-100%) | - | - | - | - | - |
| multipage_table | 13 | 12 | 13/13 (77-100%) | 6/13 (23-71%) | 11/13 (58-96%) | - | - | - | - | - |
| near_duplicate | 15 | 14 | 14/15 (70-99%) | 7/15 (25-70%) | 11/15 (48-89%) | - | - | - | - | - |
| near_identical_rows | 1 | 1 | 1/1 (21-100%) | 0/1 (0-79%) | 0/1 (0-79%) | - | - | - | - | - |
| near_identical_tables | 6 | 2 | 6/6 (61-100%) | 6/6 (61-100%) | 6/6 (61-100%) | - | - | - | - | - |
| non_first_column | 24 | 24 | 24/24 (86-100%) | 15/24 (43-79%) | 22/24 (74-98%) | - | - | - | - | - |
| non_first_row | 45 | 43 | 45/45 (92-100%) | 32/45 (57-82%) | 42/45 (82-98%) | - | - | - | - | - |
| non_first_row_col | 11 | 9 | 11/11 (74-100%) | 9/11 (52-95%) | 11/11 (74-100%) | - | - | - | - | - |
| numeric_precision | 17 | 16 | 16/17 (73-99%) | 13/17 (53-90%) | 16/17 (73-99%) | - | - | - | - | - |
| numeric_weight | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| other_state | 2 | 0 | - | - | - | - | - | - | - | - |
| out_of_scope | 18 | 0 | - | - | - | - | - | - | - | - |
| page_footnote | 1 | 1 | 0/1 (0-79%) | 0/1 (0-79%) | 0/1 (0-79%) | - | - | - | - | - |
| phrasing_drift | 11 | 11 | 11/11 (74-100%) | 7/11 (35-85%) | 10/11 (62-98%) | - | - | - | - | - |
| precision | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| printed_vs_pdf | 45 | 41 | 44/45 (88-100%) | 30/45 (52-79%) | 38/45 (71-92%) | - | - | - | - | - |
| printed_vs_pdf_page | 6 | 6 | 6/6 (61-100%) | 2/6 (10-70%) | 4/6 (30-90%) | - | - | - | - | - |
| ratio_value | 1 | 1 | 1/1 (21-100%) | 1/1 (21-100%) | 1/1 (21-100%) | - | - | - | - | - |
| roman_front_matter | 2 | 2 | 2/2 (34-100%) | 0/2 (0-66%) | 0/2 (0-66%) | - | - | - | - | - |
| rotated | 10 | 8 | 10/10 (72-100%) | 6/10 (31-83%) | 7/10 (40-89%) | - | - | - | - | - |
| rotated_text | 13 | 10 | 12/13 (67-99%) | 6/13 (23-71%) | 9/13 (42-87%) | - | - | - | - | - |
| scan | 15 | 13 | 15/15 (80-100%) | 12/15 (55-93%) | 15/15 (80-100%) | - | - | - | - | - |
| scanned_page | 6 | 6 | 5/6 (44-97%) | 3/6 (19-81%) | 5/6 (44-97%) | - | - | - | - | - |
| table_caption_named | 3 | 3 | 3/3 (44-100%) | 2/3 (21-94%) | 3/3 (44-100%) | - | - | - | - | - |
| table_id | 22 | 18 | 21/21 (85-100%) | 18/21 (65-95%) | 21/21 (85-100%) | - | - | - | - | - |
| table_note | 4 | 4 | 4/4 (51-100%) | 2/4 (15-85%) | 3/4 (30-95%) | - | - | - | - | - |
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
| cross-division | 218 | 155 | 187/192 (94-99%) | 129/192 (60-73%) | 167/192 (81-91%) | - | - | - | - | - |
| same division | 14 | 12 | 12/12 (76-100%) | 9/12 (47-91%) | 11/12 (65-99%) | - | - | - | - | - |
