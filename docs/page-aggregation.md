# Page aggregation and fusion settings (DAR-657)

Retrieval-stage measurements on the dev sets, with `prototype.image_table_check measure --index <name>=hosted/index` and the setting in the environment: the 15 image/table questions of `docs/image-table-retrieval-test.md` and the 83 known-page questions of `prototype.stress_test`. Same committed index (no rebuild), reranker on, `TOP_K` 5. Time per question is left out: the runs shared the CPU with other workers, so those numbers mean nothing.

| setting | keyword search | 15 image/table: right page in top 5 | right page #1 | 83 known-page: right page in top 5 | MRR | right document |
|---|---|---|---|---|---|---|
| default (`PAGE_AGGREGATION=off`, `FUSION_WEIGHTS=1,1`) | off | 14/15 | 12/15 | 74/83 | 0.736 | 82/83 |
| default | **on (shipped)** | **14/15** | **12/15** | **77/83** | **0.756** | **83/83** |
| `PAGE_AGGREGATION=sum` | off | 13/15 | 13/15 | 71/83 | 0.690 | 81/83 |
| `PAGE_AGGREGATION=sum` | on | 13/15 | 13/15 | 73/83 | 0.709 | 81/83 |
| `PAGE_AGGREGATION=max` | off | 14/15 | 12/15 | 72/83 | 0.719 | 81/83 |
| `PAGE_AGGREGATION=max` | on | 14/15 | 12/15 | 75/83 | 0.740 | 81/83 |
| `FUSION_WEIGHTS=1,2` | on | 14/15 | 12/15 | 78/83 | 0.759 | 82/83 |

## What it shows

- Page aggregation lowers hit@5 on both sets. With `MAX_CHUNKS_PER_PAGE=2`, the top page's second chunk takes a top-5 slot that a different page held before, and on several questions that page was the gold one. `sum` does what it was meant to do on split table pages: the concrete PCB deflection question (`wztc-pcb-concrete`, TMP p.38) goes from #2 to #1 and T14 from #4 to #1. But `tmsd-turn-radius`, A2, T10, T13 and U17 drop out of the top 5, and A5, U1, U12 and U13 lose their #1. It loses more than it gains.
- `FUSION_WEIGHTS=1,2` (keyword ranking counted twice) gains one known-page question and loses one right document: a wash.
- The defaults stay as they were (aggregation off, fusion 1,1, RRF k 60, BM25 1.2 and 0.75), so the shipped ranking is unchanged. The locked question set (DAR-653) makes the final call in DAR-652's last phase. `PAGE_AGGREGATION=sum` with `MAX_CHUNKS_PER_PAGE=1` (the page still ranks by both chunks, but gives only one to the top 5) is the next variant worth trying there.

## Reproducing

```bash
set MODEL_CACHE_DIR=R:\_code_\RAG-Chatbot\hosted\models
set PAGE_AGGREGATION=sum
.venv\Scripts\python -m prototype.image_table_check measure --index sum=hosted/index --out <scratch>/sum.json
```

`prototype.search` and `prototype.stress_test` read the same settings (`divrag.config.retrieval_options`), so they rank as the app would.
