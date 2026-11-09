# Reranker and page aggregation pick (DAR-657, DAR-652 final phase)

Retrieval stage only (no model calls), on the index rebuilt after all DAR-652 changes (13,240 chunks). A question is found when a chunk of the gold document on a gold PDF page is in the top 5 (hit@5) or first (hit@1). Counts are over the answerable items; brackets are 95% Wilson intervals.

## How the pick was made

1. Every variant ran on the **tuning split** (41 answerable items). The rule was to take the best hit@1, then the best hit@5, and to keep the current default unless a variant beat it on both.
2. The same variants then ran once on the **locked split** (204 answerable items) to report them, as DAR-657 asks. The locked numbers were not used to choose between variants.

## Tuning split (41 answerable)

| variant | hit@1 | hit@5 |
|---|---|---|
| MiniLM-L-6, every chunk (old default) | 32 | 38 |
| MiniLM-L-6, page aggregation max | 32 | 37 |
| MiniLM-L-6, page aggregation sum | 27 | 38 |
| MiniLM-L-6, at most 3 chunks per document | 32 | 35 |
| **MiniLM-L-6, text chunks only (RERANK_TEXT_ONLY)** | **33** | **39** |
| text chunks only, page aggregation max | 33 | 38 |
| no reranker (fused order) | 31 | 39 |
| MiniLM-L-12, every chunk | 32 | 38 |
| MiniLM-L-12, page aggregation max | 32 | 37 |

## Locked split (204 answerable)

| variant | right document | hit@1 | hit@5 |
|---|---|---|---|
| MiniLM-L-6, every chunk (old default) | 200 (95-99%) | 147 (66-78%) | 180 (83-92%) |
| no reranker | 201 (96-99%) | 136 (60-73%) | 183 (85-93%) |
| **MiniLM-L-6, text chunks only** | 200 (95-99%) | **152 (68-80%)** | **183 (85-93%)** |
| MiniLM-L-12, every chunk | 200 (95-99%) | 147 (66-78%) | 180 (83-92%) |
| MiniLM-L-6, page aggregation max | 199 (94-99%) | 147 (66-78%) | 177 (81-91%) |
| MiniLM-L-6, page aggregation sum | 199 (94-99%) | 138 (61-74%) | 178 (82-91%) |

Per-variant reports: `locked-retrieval-*.md` in this folder.

## Decision

- **RERANK_TEXT_ONLY is now on by default.** It was best on the tuning split and has the same lead on the locked split: +5 hit@1 and +3 hit@5. The difference is inside the intervals, so it is a small gain, not a proven one. It costs less than reranking every chunk, because tables are not sent to the cross-encoder.
- **MiniLM-L-6 stays the reranker.** MiniLM-L-12 ranks the same pages first, at about 6 times the model size (docs/reranker-ab.md). bge-reranker-base is over the Vercel bundle room, and jina-turbo ranked below no reranker on the dev sets.
- **Page aggregation stays off.** Both max and sum are lower on hit@5, and sum is also lower on hit@1.
- **No reranker** has the same hit@5 as text-only but 16 fewer first-place hits. The answer prompt numbers passages in rank order, so first place matters.
