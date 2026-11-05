# Table quality at index time (DAR-655)

`prototype/table_quality.py` checks each chunk that holds a Markdown table and writes the result into a `flags` list on the chunk in `chunks.json`. `prototype/build_report.py` counts those flags per document, next to the page coverage. The report for the committed index is in [`build-report-current.json`](build-report-current.json). It was produced from `hosted/index` at commit 8feefe6, with no rebuild:

    py -m prototype.build_report --index hosted/index --out docs/build-report-current.json --markdown

A build writes the same report with `py -m prototype.ingest ... --report PATH`. That run also stores `flags` on the chunks.

## Flags

| Flag | Meaning |
|---|---|
| `empty_header` | A header cell outside the first column is blank. The first column is left out because a blank corner above the row labels is normal. |
| `column_mismatch` | A row has a different number of cells from the header. |
| `low_text` | The rows hold almost no letters or digits, as when a drawing's title block is read as a table. |
| `fragmented_header` | Header or row-label text is broken into pieces: an unbalanced bracket (`eed(mph`, `)`), or a header made mostly of 1–2-letter scraps. |
| `no_caption` | Neither the chunk nor its context line contains a "Table N" / "Figure N" caption. |
| `rotated` | More than 30% of the page's characters are set at an angle, measured as the reader sees the page (after the page's `/Rotate` is applied). |
| `ocr_low_conf` | Set by the OCR unit (U16). This step keeps it on the chunk but never sets it. |

The known bad case is the TMP Design Manual deflection table on PDF p. 37, where "Offset (ft)" is split down the first column as `ft)`, `et (`, `ffs`, `O`. Both of its chunks are flagged `empty_header` and `fragmented_header`, and so are the two chunks of the matching table on p. 38. The page is not flagged `rotated`: only about 1% of its characters run at an angle, so the damage shows up in the header text instead.

## Counts (committed index)

"Beyond no_caption" counts table chunks with at least one flag other than `no_caption`, meaning tables whose text was read badly. Many manuals print no table numbers at all (bpguidebook: 68 of 68 tables), so `no_caption` alone says little about extraction quality.

| Division | Chunks | Table chunks | Flagged | Beyond no_caption | empty_header | column_mismatch | low_text | rotated | no_caption | fragmented_header |
|---|---|---|---|---|---|---|---|---|---|---|
| wztc | 4673 | 764 | 561 | 165 | 129 | 2 | 3 | 11 | 475 | 67 |
| utilities | 1789 | 167 | 125 | 45 | 31 | 0 | 1 | 0 | 106 | 16 |
| tmsd | 4284 | 956 | 712 | 538 | 461 | 0 | 6 | 6 | 650 | 82 |
| **all** | 10746 | 1887 | 1398 | 748 | 621 | 2 | 10 | 17 | 1231 | 165 |

Worst documents by share of tables flagged beyond `no_caption` (only documents with at least 5 table chunks):

| Document | Division | Table chunks | Beyond no_caption | Share | Top flags |
|---|---|---|---|---|---|
| L18_TSLG_Guide.pdf | tmsd | 380 | 358 | 94% | empty_header 358 |
| 09. At Grade Intersections.pdf | tmsd | 24 | 21 | 88% | empty_header 14, rotated 6, fragmented_header 2 |
| CFR-2024-title23-vol1-part655.pdf | tmsd | 12 | 10 | 83% | empty_header 9, fragmented_header 1, low_text 1 |
| 04100.pdf | tmsd | 112 | 87 | 78% | fragmented_header 60, empty_header 29 |
| trans_mgmt_plans.pdf | wztc | 63 | 28 | 44% | empty_header 24, fragmented_header 19, low_text 3 |
| Division 11 Combined.pdf | wztc | 7 | 3 | 43% | empty_header 2, fragmented_header 1 |
| TMP Design Manual (Combined, No Links).pdf | wztc | 31 | 12 | 39% | empty_header 12, fragmented_header 8, column_mismatch 2 |
| 01102.pdf | tmsd | 16 | 6 | 38% | fragmented_header 2, empty_header 2, low_text 2 |
| STEP-guide-improving-ped-safety.pdf | tmsd | 8 | 3 | 38% | empty_header 3, fragmented_header 1 |
| 20220713 NCDOT UAM Ver 2-0.pdf | utilities | 63 | 22 | 35% | empty_header 14, fragmented_header 9, low_text 1 |
| fhwahop12005.pdf | wztc | 161 | 56 | 35% | empty_header 47, fragmented_header 21 |

`py -m prototype.build_report --markdown` prints the full list of 20.

## Page coverage

Across the 58 documents, 88 PDF pages produced no chunk (`empty_text_pages`). The most are in fhwahop09021.pdf (15), 04091.pdf (14) and rule_guide.pdf (12). Another 158 pages have chunks but no text layer, so the `--ocr` build read them with OCR (`ocr_pages`). Most of those are in 010604.pdf (88), the UAM (25) and Chapter_2.pdf (22).

## Notes

- The L18 TSLG guide's 358 `empty_header` chunks are continuation pieces of one 9-column legal index table that runs for about 700 pages ("Topic | Overview | Federal Regulations | U.S. Code | ..."). The real header is printed only on the first page. On every later page, a data row whose regulation columns are blank sits where the header should be (`|Abandonment (service roads)|...|136-89.55||1977-0464|||`). So the flag catches a real defect: those chunks do not say which column a citation belongs to. Repeating the header across pages is the multi-page merge unit's job (U10).
- The standalone report always recomputes the flags from the chunk text and the PDFs in `hosted/documents/`. A change to a threshold therefore shows up without rebuilding the index.
