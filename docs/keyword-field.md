# Caption/ID keyword field and question parsing (DAR-657)

## What changed

The keyword (BM25) search added in DAR-651 scored one field per chunk: its search text (context line + text). A question that names a table ("What does Table 3-2 give...") was tokenized to `table`, `3`, `2`. Every table page has those, so the captioned page got no special credit.

- **Tokenizer** (`hosted/divrag/keyword.py`). It keeps identifiers whole: `6H-3`, `3-2`, `A-3`, `04-20340` and `1/2` are one token each, followed by their pieces, so "Table 3 2" written loosely still matches. A hyphenated word with no digit ("right-of-way") is split into its words. Units are folded: `12'`, `12 feet` and `12-foot` become `12 ft`. `25.37"` and `6 in.` become `in`, `%` becomes `pct`, and `1,500` becomes `1500`. A bare "in" stays a stopword.
- **Caption/ID field** (`index_file.field_text`). Each chunk gets a second, short BM25 field holding:
  - the page's figure and table captions, from the context line's caption segments and from caption-style lines in the text;
  - every table, figure, section, sheet or standard number the text names, spelled as the question parser spells it ("Fig. 2-1" becomes "Figure 2-1");
  - document codes (`04-20340`, `04091`, but not the decimals of `0.0200`);
  - the document's title and file name, and the chunk's section.

  The page's own caption IDs are counted once more than IDs it only cross-references, so "see Table 3-2" does not outrank the table itself. The context line is parsed by segment shape, not position, so a later `printed p.X` segment does not break it.
- **Score**: body + `KEYWORD_FIELD_BOOST` × field, as one ranking (BM25F-style). The division filter is still applied inside the search: the field never surfaces another division's chunk.
- **Question parsing** (`hosted/divrag/query.py`). Deterministic regexes find "Table 3-2", "Fig 5", "Section 4.2", "Sheet 1", "Standard 1101.01" and document codes. Their number tokens (not the word "table") count `KEYWORD_ID_BOOST` times in the field. This is a boost, never a filter: a chunk without the ID still ranks by its body. The vector search still gets the question as asked.
- **File format**: `bm25.npz` is now version 2 (`version` entry plus `field_*` arrays). A version-1 file still loads: `IndexFile.load` rebuilds the whole keyword index from `chunks.json` and logs a warning, because the old body used the old tokenizer. `hosted/scripts/rebuild_keyword_index.py` regenerates `hosted/index/bm25.npz` from the committed chunks without embedding anything (about 12 s). The committed file was regenerated with it.

Settings: `KEYWORD_FIELD` (`on`), `KEYWORD_FIELD_BOOST` (1.5), `KEYWORD_ID_BOOST` (2). `/api/health` reports all three.

## Measurements

Retrieval only, no model calls. The questions are the 15 image/table questions (`prototype/image_table_check.py`) and the 83 known-page questions (`prototype/stress_test.py`). "Before" is `prototype.image_table_check measure` run on `main` (8feefe6). The variants are the same scoring with this branch's code and regenerated `bm25.npz`, models loaded once.

| setting | 15: right doc | 15: right page in top 5 | 15: right page #1 | 83: right page in top 5 | 83: MRR | 83: right doc in top 5 |
|---|---|---|---|---|---|---|
| main, vector only | 15/15 | 14/15 | 12/15 | 74/83 | 0.736 | 82/83 |
| main, vector + keyword (DAR-651) | 15/15 | 14/15 | 12/15 | 77/83 | 0.756 | 83/83 |
| this branch, field off (new tokenizer only) | 15/15 | 14/15 | 12/15 | 77/83 | 0.756 | 83/83 |
| field 1, ID 1 | 15/15 | 14/15 | 12/15 | 77/83 | 0.756 | 82/83 |
| **field 1.5, ID 2 (default)** | 15/15 | 14/15 | 12/15 | **77/83** | **0.764** | 82/83 |
| field 2, ID 1 / 2 / 4 | 15/15 | 14/15 | 12/15 | 76/83 | 0.752 | 82/83 |
| field 3, ID 2 | 15/15 | 14/15 | 12/15 | 74/83 | 0.742 | 81/83 |

- At 1.5 the field keeps every hit the DAR-651 search had and slightly improves the rank of the right page (MRR 0.756 to 0.764). At 2 the known-page question T25 drops out of the top 5, and at 3 T17 and U17 drop out too. At those boosts the field's title and section words start to outweigh the body.
- The misses are the same in every setting: `tmsd-guardrail-l1` among the 15, and A1, A6, T1, T7, T8 and U14 among the 83.
- **None of the 98 questions names a table, figure or document number**, so these sets cannot show what the ID boost is for. ID boosts 1, 2 and 4 score identically on them. The ID behaviour is covered by the unit tests: "Table 3-2" ranks the captioned chunk first, the captioned page beats a page that only cites the table, and the label word is not boosted. It needs a locked-set item of type `table_id` (DAR-652) to measure.
- Timings are not reported. The machine was shared with other jobs during the runs, and per-question times varied threefold between identical settings.

## End-to-end check

Server on port 8113 from this branch, run before the default was lowered to 1.5 (`/api/health` reported `keyword_field: true, keyword_field_boost: 2.0, keyword_id_boost: 2.0`; the boost is applied at query time, so `bm25.npz` is the same). The question was "What does Table 3-1 in the TMP Design Manual give for a 40 mph design speed?" (asker utilities, target wztc). It came back with a single source, TMP Design Manual p.58: the page captioned "Table 3-1 Clear-zone distance in feet...". The answer quoted its 40 mph rows (7-10 ft for ADT under 750 on 1V:6H or flatter). The TMP manual has no plain "Table 3"; its table captions are 3-1 (p.58) and 3-2 (p.59). `python -m prototype.search --division wztc "Table 3 deflection 40 mph"` also ranks p.58 first.

## Known limits

- A closing double quote right after a number (`"Route 54"`) is read as an inch mark. In these manuals a number followed by `"` is almost always inches.
- "Table 3" boosts the token `3`, which the fields of Tables 3-1 and 3-2 also hold, so a bare number singles out its table less sharply than "3-2" does.
