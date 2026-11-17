# Lists and tables that run over a page break (DAR-736)

Nov 17, 2026. DAR-732 found that 5 of the 7 incomplete answers on the OpenAI held-out run were lists that continue on the next page, and the model only got the first page. `with_following` (add the next chunk for the top two hits) didn't help: that chunk is often on the same page.

## What changed

`hosted/divrag/retrieval.py`, `hosted/divrag/answer.py`:

- For **every** passage the model reads (top 5 plus the following chunks, and the second look's extra passages), when the passage's page **ends in a list or table that the next page continues**, the next page's first chunk comes along. The mirror case too: a passage that **starts** a page with list items or table rows that the previous page started brings the previous page's last chunk.
- "Runs over" means: the page's last line (after dropping folios, footnotes and running footers) is a list item or table row, or ends leading on (`:`, `;`, `,`, "and", "or"); **and** the next page's first line (after the same cleanup) is a list item or table row. Contents pages (leader dots) never count.
- When the continuation isn't in the passages (the page is the document's last, or the next page starts with something else after a lead-on line), the passage gets a note, "This list or table may continue on the next page", and the prompt tells the model to say so if it answers from it.

Not taken: also counting a page whose last **sentence** is unfinished. It added context to 194 questions instead of 137 (+34% mean context instead of +15%) for 2 more gold pages (247 instead of 245 of 272), so the cost was not worth it.

## Context size and cost

Retrieval only, the 286 held-out (locked split) questions, site defaults (`TOP_K` 5, rerank and keyword search on):

| | Before | After |
|---|---|---|
| Passage text a question (mean) | 10,536 characters | 12,097 (+14.8%) |
| Questions whose passages changed | | 137 of 286; +3,261 characters on those |
| Largest increase | | +10,732 characters |
| Chunks a question (mean) | 6.34 | 7.29 |
| Gold pages among the passages | 239 of 272 | 245 of 272 |
| Passages marked "may continue" | | 8 questions |

Cost on `gpt-6.1-terra` ($1 per million input tokens, about 4 characters a token): about **+390 input tokens, +$0.0004 a question** on average (+$0.0008 on a question that changes), about +13% of the first call's input; about +$0.11 for a full held-out run. The free models cost nothing more. The 10,732-character worst case is still far under the model's context limit and the request's time budget (the paired run's slowest answer took 12.1 s after against 14.7 s before; the mean stayed 2.8 s).

## Checks

### The five DAR-732 page-break items

utilities-h072, utilities-h073, utilities-h074, wztc-h032, wztc-h033, run locally with the free models: all 5 answer with the full list (`value_ok` 5/5). These were read in detail for DAR-732, so this is a development check, not a measurement (DAR-737 retired them from the held-out set).

### Paired run on the questions it changes

The 137 held-out questions whose passages change, each asked twice with the free models (`nvidia/nemotron-3-ultra-550b-a55b:free` first), once on main and once on this branch, both scored with the DAR-737 scorer:

| | Before | After |
|---|---|---|
| Confident wrong | 10 / 137 | **5 / 137** |
| Value right | 101 / 112 | 105 / 112 |
| Strict (value and page) | 89 / 112 | 95 / 112 |
| Answerable declined (over-refusal) | 3 / 117 | 3 / 117 |
| Must-refuse answered | 2 / 20 | 1 / 20 |
| Errors | 0 | 0 |

- No question became confident wrong, and none lost its right value.
- The 5 that stopped being confident wrong are utilities-h072, utilities-h073, wztc-h032, wztc-h033 (page-break lists, now complete) and wztc-h043 (a must-refuse question, now declined instead of answered). All five were read for DAR-732, so the gain is on development items. On the other 132 changed questions the confident-wrong and value counts didn't move: no harm, no measured gain.
- utilities-h074 was already right before on the free model.

The other 149 questions get the same passages as before, so their answers can't change.

## Tests

`tests/test_hosted_index_file.py`:
- a list split over two pages;
- a list that a passage starting a page continues from the previous page;
- a table split over two pages;
- cases that must add nothing: a page that ends its list, a contents page, a page too far from the hit;
- a list item against a plain sentence;
- the "may continue" mark.

`tests/test_hosted_answer.py`: the note and the prompt rule.
