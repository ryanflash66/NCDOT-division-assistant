# RAGAS judge on openai-site-dar738

- Answers: site:ncdot-division-assistant-iota.vercel.app:gpt-6.1-terra+nvidia/nemotron-3-ultra-550b-a55b:free+nvidia/nemotron-3.5-super-vl:free+google/gemma-4-31b-it:free@0a027cfc7885#dar738 (from `docs/heldout-set/openai-site-dar738.json`, no new answer calls)
- Judge: api.openai.com:gpt-6.1-terra
- Coverage: 270/270 judged
- Passages rebuilt on the local index: 286 answers, cited excerpts found 274/274, answers with a missing excerpt 0, retried answers (wider passages) 28

| metric | all | wztc | utilities | tmsd |
|---|---|---|---|---|
| faithfulness | 0.98 [0.97-0.99] (n=261) | 1.00 [0.99-1.00] (n=85) | 0.97 [0.93-0.99] (n=88) | 0.98 [0.95-0.99] (n=88) |
| answer_relevancy | 0.81 [0.79-0.84] (n=270) | 0.83 [0.79-0.86] (n=86) | 0.80 [0.74-0.84] (n=91) | 0.82 [0.77-0.86] (n=93) |
| context_precision | 0.81 [0.77-0.85] (n=256) | 0.74 [0.67-0.81] (n=79) | 0.84 [0.77-0.91] (n=87) | 0.84 [0.78-0.90] (n=90) |
| context_recall | 0.96 [0.93-0.98] (n=256) | 0.99 [0.96-1.00] (n=79) | 0.93 [0.87-0.98] (n=87) | 0.95 [0.91-0.99] (n=90) |
| page_hit | 0.90 [0.87-0.94] (n=256) | 0.90 [0.82-0.96] (n=79) | 0.91 [0.85-0.97] (n=87) | 0.90 [0.83-0.96] (n=90) |
| page_rr | 0.76 [0.71-0.80] (n=256) | 0.72 [0.64-0.80] (n=79) | 0.80 [0.72-0.86] (n=87) | 0.75 [0.67-0.82] (n=90) |
| page_precision | 0.73 [0.69-0.78] (n=256) | 0.70 [0.61-0.77] (n=79) | 0.77 [0.69-0.83] (n=87) | 0.74 [0.66-0.81] (n=90) |
| page_recall | 0.95 [0.92-0.97] (n=256) | 0.96 [0.91-1.00] (n=79) | 0.94 [0.89-0.99] (n=87) | 0.93 [0.88-0.98] (n=90) |
| table_pass | - | - | - | - |
| correct_refusal | 0.53 [0.33-0.70] (n=30) | 0.42 [0.17-0.67] (n=12) | 0.60 [0.30-0.90] (n=10) | 0.62 [0.25-0.88] (n=8) |

Means with 95% bootstrap intervals and n. Page metrics are on (document, PDF page) pairs. See evaluation/METRICS.md for the definitions.
