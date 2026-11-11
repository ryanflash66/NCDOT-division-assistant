# DAR-656: which PDF reader

**What changed.** Nothing in the build: the bake-off kept the current reader (pymupdf4llm with pymupdf-layout table boxes and RapidOCR) for every page (decision log D7).

**Merged from:** `ryanflash166/dar-656-extraction-bakeoff` (d0868dc); main via PR #41 (7489cdf).

## Before and after on the same pages

117 hard pages from 38 documents, chosen from the corpus audit (tables, rotated text, scans, drawings, page breaks), all run on CPU. From `docs/extraction-bakeoff.md`:

| reader | table cells right (30 checked by hand) | numbers kept vs text layer | no-text pages read | CPU s per page |
|---|---|---|---|---|
| pymupdf4llm + RapidOCR (kept) | 24/30 (63–90%) | 0.95 | 21/26 (62–91%) | 2.5 |
| Docling 2.147 | 23/30 (59–88%) | 0.87 | 22/26 (66–94%) | 19.3 |
| MinerU 4.1.7 (medium) | 22/30 (56–86%) | 0.79 | 21/26 (62–91%) | 6.2 |

MinerU's high mode (a vision model) took up to 1,219 s on one page and was no more accurate. The intervals overlap: no reader is clearly better on cells, and the current one keeps the most numbers and is the fastest.

Not on the locked set: this ticket compared readers on pages, not answers.

**Raw results:** `docs/extraction-bakeoff/results.json` and `docs/extraction-bakeoff.md`.

## Reproduce

```bash
.venv\Scripts\python -m prototype.bakeoff.select_pages --audit .handoff\redo-nov4\corpus-audit.json --documents hosted\documents
.venv\Scripts\python -m prototype.bakeoff.run --candidate pymupdf4llm --out <out>
.venv\Scripts\python -m prototype.bakeoff.run --candidate docling --out <out>
.venv\Scripts\python -m prototype.bakeoff.report --out <out>
```

Commit d0868dc. The full list of candidates and their install steps is in `docs/extraction-bakeoff.md`.

## Open

- A paid vision model for drawings and failed scans: about USD 4.7 to 7.8 for the 1,178 flagged pages at list price. Dr. Namian's decision; nothing was run.
