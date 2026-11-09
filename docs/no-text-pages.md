# Pages with no text in the index (DAR-658)

Written by `python -m prototype.no_text_pages`. Pages come from the corpus audit
(`.handoff/redo-nov4/corpus-audit.json`) checked against the committed index; "indexed now"
is from `index`. Counts are characters of text-chunk text on the page
(figure chunks excluded). "Not rebuilt" pages are in divisions this run didn't rebuild;
rerun after the full rebuild.

## Image-only pages (6: 6 not fixed)

Images, under 10 characters of text layer, not "intentionally left blank", and no indexed text before.

| Document | PDF page | Text layer (chars) | Images | Indexed before | Indexed now | Status | Reason / flags |
|---|---|---|---|---|---|---|---|
| utilities/010604.pdf | 4 | 0 | 33 | 0 | 0 | not fixed | blank scanned page (a white page image; nothing to read) |
| utilities/010604.pdf | 238 | 0 | 1 | 0 | 0 | not fixed | blank scanned page (OCR reads one digit at 0.53 confidence) |
| utilities/010604.pdf | 308 | 0 | 1 | 0 | 0 | not fixed | blank scanned page (a white page image; nothing to read) |
| utilities/010604.pdf | 314 | 0 | 1 | 0 | 0 | not fixed | blank scanned page (a white page image; nothing to read) |
| utilities/010604.pdf | 315 | 0 | 1 | 0 | 0 | not fixed | blank scanned page (a white page image; nothing to read) |
| wztc/Chapter_5.pdf | 14 | 0 | 187 | 0 | 0 | not fixed | photo page: OCR reads only the running header and the sign 'SHOULDER CLOSED AHEAD' |

## Text-loss pages (5: 5 not fixed)

200+ characters of text layer, under 50% of them indexed before.

| Document | PDF page | Text layer (chars) | Images | Indexed before | Indexed now | Status | Reason / flags |
|---|---|---|---|---|---|---|---|
| tmsd/Policy on Access Manual.pdf | 83 | 2200 | 0 | 1057 | 1057 | not fixed | appeal checklist form: the blanks and check boxes are dropped, the questions are indexed |
| tmsd/fhwa_hop_08_024.pdf | 219 | 1823 | 0 | 567 | 567 | not fixed | table with rotated header text (216 rotated characters); text-layer fix, not OCR |
| tmsd/fhwa_hop_08_024.pdf | 230 | 3035 | 0 | 951 | 951 | not fixed | table with rotated header text (408 rotated characters); text-layer fix, not OCR |
| tmsd/fhwa_hop_08_024.pdf | 233 | 9000 | 0 | 1553 | 1553 | not fixed | table with rotated header text (453 rotated characters); text-layer fix, not OCR |
| utilities/20220713 NCDOT UAM Ver 2-0.pdf | 286 | 2095 | 35 | 0 | 0 | not fixed | map legend printed sideways: a rotated text layer pymupdf4llm drops; text-layer fix, not OCR (no OCR runs on a page with a text layer) |

## Pages that lost all their text (0)

None.

## Audited PDFs no division loads (2)

Their pages are left out above: no build reads them. The scanned ones read cleanly with
`--ocr` (the Revised Rumble Strip Guidelines memo at 0.99 confidence, the Work Zone Safety
and Mobility Policy at 0.98-0.99), so adding them to divisions.py is enough.

- tmsd/Revised Rumble Strip Guidelines.pdf
- wztc/WZSafety_and_Mobility.pdf
