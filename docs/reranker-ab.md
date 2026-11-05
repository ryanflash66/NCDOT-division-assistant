# Reranker A/B on the dev sets (DAR-657)

Retrieval stage only: each question searched once (vector top 40 in its division fused with the keyword search), then each variant reranks the same 40. Found = a chunk of the gold document on a gold page; hit@1, hit@5 and MRR over the top 5. Seconds are rerank time per question, on top of 0.111 s of search. Peak RSS is the variant's own process (index chunks + model). The default reranker is unchanged; the locked-set run picks.

Sets: image_table (15), known_pages (83), tuning (23).

Stopped at the time limit, scored on the questions finished: minilm-l12 ran 53 of 121 questions in 15 min; jina-turbo ran 120 of 121 questions in 15 min.

| variant | image_table hit@1 | hit@5 | MRR | known_pages hit@1 | hit@5 | MRR | tuning hit@1 | hit@5 | MRR | s/question | load s | peak RSS MB | model MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| none | 10/15 | 14/15 | 0.778 | 46/83 | 73/83 | 0.689 | 17/23 | 21/23 | 0.812 | 0.000 | 0.0 | 112.3 | - |
| minilm-l6 | 12/15 | 14/15 | 0.867 | 54/83 | 77/83 | 0.756 | 18/23 | 20/23 | 0.802 | 5.564 | 42.29 | 244.4 | 22.8 |
| minilm-l12 | 13/15 | 14/15 | 0.900 | 18/38 | 33/38 | 0.627 | - | - | - | 16.665 | 3.99 | 333.4 | 128.2 |
| bge-base | skipped: BAAI/bge-reranker-base is a 1.04 GB download (limit 1.0 GB) | | | | | | | | | | | | |
| jina-turbo | 13/15 | 14/15 | 0.900 | 39/83 | 67/83 | 0.603 | 17/22 | 19/22 | 0.811 | 7.031 | 43.52 | 405.7 | 146.2 |
| text-only | 12/15 | 14/15 | 0.856 | 52/83 | 77/83 | 0.746 | 19/23 | 21/23 | 0.846 | 4.206 | 20.34 | 226.1 | 22.8 |

## Notes (Nov 5 run)

- Command: `MODEL_CACHE_DIR=<scratch> python -m evaluation.rerank_ab --locked tmsd.json --locked utilities.json` on the committed `hosted/index/`, with the `tmsd` and `utilities` locked-set files from their DAR-653 branches. Only their `tuning` split is read: 14 + 9 = 23 answerable items. The `wztc` set wasn't committed yet, so the tuning set is 23 questions rather than the planned ~90. Rerun with `--locked evaluation/locked/wztc.json` after the sets merge.
- **The timings are relative only.** The machine was at 100% CPU on all 16 cores because the other DAR-652 workers were running at the same time. MiniLM-L-6 reranked 40 passages in 5.6 s here, against about 0.5 s per question in the DAR-651 `measure` runs (`docs/image-table-retrieval/measure-fix1.json`). Hit rates and MRR don't depend on load.
- MiniLM-L-12 hit the 15-minute limit after 53 of the 121 questions (15 image/table and 38 known-page). On those same 53 questions: none hit@1 25, hit@5 47, MRR 0.632; MiniLM-L-6 31 / 47 / 0.705; L-12 31 / 47 / 0.704; jina-turbo 26 / 40 / 0.601; text-only 31 / 47 / 0.705. So L-12 matches L-6 at about 6x the model size and 3x the time.
- bge-reranker-base was skipped because fastembed lists it as a 1.04 GB download. That is also well past the room left in the Vercel bundle (about 220 MB for models; see `MAX_MODELS_MB` in `hosted/scripts/fetch_models.py`).
- jina-reranker-v1-turbo-en ranks below no reranker on the 83 known-page questions (hit@5 67 vs 73).
- Text-only: the committed index has no `kind` tags yet, so tables are found by their Markdown pipe table. That gives about 5.8 table chunks in each pool of 40. It ties MiniLM-L-6 on hit@5 and is ahead on the tuning items (hit@1 19 vs 18, hit@5 21 vs 20). Most of the 23 tuning items are text questions, so this needs the locked-set run before anything is read into it.
- Peak RSS includes the index chunks (about 110 MB without a model). Model MB is the model's folder in the cache, with each file counted once.
