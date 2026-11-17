# DAR-737: 28 replacement held-out items, authoring notes

File: `.handoff/dar-737/new-items.json` (28 items, all `locked`). The items are written as dicts in `items.py`, and
`build.py` turns them into that file. build.py assigns the ids in spec order, adds `replaces`, computes the split with
`evaluation.locked.split_of` and runs every check listed under Verification. Its last run printed
`validate_items + tag_errors: ok` and `PROBLEMS: none` (log: `build.log`).

The work stayed blind throughout. I read only the PDFs, the dar-661 OCR text and caches, `hosted/divrag/divisions.py`,
the scorer and validator code, the three authoring notes and the retired items in `evaluation/heldout/*.json`. I did
not open any run report or result, `hosted/index/` or `docs/redo-reports/`, and I ran no model.

## Items

Each line gives: new id, the retired id it replaces, document, PDF page(s), printed page(s), page kind, and how the
item was verified.

- wztc-h101, replaces wztc-h031. trans_mgmt_plans.pdf, PDF 33-34, printed 3-3 / 3-4. List over a page break (TMP roles, section 3.3). page_text_match; list-break check passed (3 parts only on the first page, 2 only on the second).
- wztc-h102, replaces wztc-h032. wzi_guide.pdf, PDF 159-160, printed A-5 / A-6. List over a page break (Woodrow Wilson Bridge EIS mitigation measures, appendix). page_text_match; list-break 5/2.
- wztc-h103, replaces wztc-h033. trans_mgmt_plans.pdf, PDF 50-51, printed 4-8 / 4-9. List over a page break (IC2 contracting strategies). page_text_match; list-break 2/2.
- wztc-h104, replaces wztc-h043. Must-refuse (revision_marks). TMP Design Manual p3 lists the post as "(Vacant)". Absence check over all 20 wztc documents and the wztc OCR: the position title occurs only on p3 (no name) and p70 (no name). accept_reply "vacant".
- wztc-h105, replaces wztc-h072. Must-refuse (not_in_documents): minimum flagger age. Absence check over all wztc text and the Chapter_2/Chapter_5 OCR. The only 3 hits are "storage/signage requirements", which are unrelated.
- wztc-h106, replaces wztc-h079. trans_mgmt_plans.pdf, PDF 98, printed B-16. Continuation page of Table B.1 (multipage table, appendix), row IIA13. page_text_match for every all_of part; the row assignment was read off the rendered page.
- wztc-h107, replaces wztc-h086. TMP Design Manual, PDF 40, printed 16. Plain text, cross-reference to WZTCS Design Manual Chapter 2.2. page_text_match.
- wztc-h108, replaces wztc-h097. wzi_guide.pdf, PDF 146, printed 9-6. Plain text, chapter page (NYSDOT's 7 intrusion countermeasures). page_text_match.
- utilities-h106, replaces utilities-h056. 010604.pdf, PDF 286, printed 270. Scanned page with no text layer and a stamp printed over the answer line (WSDOT franchise exhibit, item 20, "3½ feet"). page_image_read. The OCR text (dar-661) reads "3½/ feet", so the OCR match fails and the image reading is the evidence.
- utilities-h107, replaces utilities-h058. UAM, PDF 47, printed 2-23. Plain text that also appears in tmsd L18 p550 (19A NCAC 02B .0506). page_text_match.
- utilities-h108, replaces utilities-h066. CFR part 710, PDF 13, printed 503. Two-column CFR page, false premise (reversion clause). page_text_match; the premise does not match the value or any accept.
- utilities-h109, replaces utilities-h072. CFR part 710, PDF 11-12, printed 501 / 502. List over a page break (710.405(b) provisions). page_text_match; list-break 4/2.
- utilities-h110, replaces utilities-h073. if03014.pdf, PDF 74-75, printed B-74 / B-75. List over a page break (funding routes for pole safety). page_text_match; list-break 1/3.
- utilities-h111, replaces utilities-h074. Presentation notes, PDF 32-33, printed 30 / 31. Two slide images titled "Prior Rights Claims" (figure), a list over a page break. page_image_read for the slides; every part was also text-matched in the speaker notes on the same pages; list-break 3/3.
- utilities-h112, replaces utilities-h080. UAM, PDF 79, printed 3-6. Plain text, chapter page, inch-mark symbols (11″x17″, 8.5″x11″). page_text_match.
- utilities-h113, replaces utilities-h087. UAM, PDF 41, printed 2-17. Plain text, chapter page, false premise (25 % vs the real 15 percent). page_text_match; the premise does not match.
- utilities-h114, replaces utilities-h090. Must-refuse (not_in_documents): hours of training for utility locators. Absence check over all utilities text and the dar-661 utilities OCR found 0 hits.
- tmsd-h107, replaces tmsd-h009. RDM ch.9, PDF 9, sheet F-3A-4. Scanned drawing (Figure 3-A, 36-foot median: 4° skew gives about 385′). page_image_read; sheet id read off the image.
- tmsd-h108, replaces tmsd-h016. TODS Manual, PDF 25, printed 22. Plain text with a threshold (at least 200 feet before the main intersection; the question asks about 150 feet). page_text_match.
- tmsd-h109, replaces tmsd-h019. RDM ch.9, PDF 27, sheet T-4. Scanned table printed sideways (Table 4, merged header "Length in feet", block C43 R1=100' R2=35', row Δ=104°, column T = 76.20). page_image_read.
- tmsd-h110, replaces tmsd-h024. 04100.pdf, PDF 77, printed 67. Table, clarify (Table 12 adjustment factor for 3-4 p.m.; the answer depends on area type: 16.2 / 8.1 / 7.4). page_text_match for all 3 branches.
- tmsd-h111, replaces tmsd-h049. RDM ch.9, PDF 34, sheet F-2. Scanned figure with an equation (d = 1.47 V (J + tₐ)). page_image_read.
- tmsd-h112, replaces tmsd-h052. RDM ch.9, PDF 14, sheet F-4B. Drawing printed sideways (Figure 4, near side widening "2/3 A"); its near-identical twin is the Access manual exhibit on p89. page_image_read.
- tmsd-h113, replaces tmsd-h082. Chapter2c.pdf, PDF 52, printed 196. Plain text, clarify (ball-bank 16/14/12 degrees by speed). page_text_match for all 3 branches.
- tmsd-h114, replaces tmsd-h085. L18, PDF 265-266, printed 265 / 266. List over a page break with units (G.S. 20-118(c)(12) five-axle limits). page_text_match; list-break 4/1.
- tmsd-h115, replaces tmsd-h089. L18, PDF 554, printed 554. Plain text that also appears in UAM 4.1.7 (19A NCAC 02B .0515(g), utility refuses to relocate). page_text_match.
- tmsd-h116, replaces tmsd-h097. L18, PDF 301-302, printed 301 / 302. List over a page break (G.S. 20-158(c), devices away from intersections). page_text_match; list-break 1/1.
- tmsd-h117, replaces tmsd-h100. Must-refuse (not_in_documents): sign retroreflectivity minimum for guide signs. Absence check over all 19 tmsd documents and the tmsd OCR cache. Its 5 hits are pavement-marking units (part3 p3) and SI conversion tables (04100 p4, 04091 p4).

## Verification (build.py)

The value and every `all_of` part were checked with `normalize.value_matches` against the gold pages' text layer. For
matching only, build.py also checked two altered copies of each page: one with line-end hyphens joined and
U+2010/U+2011 hyphens and no-break spaces made plain, and one with whitespace collapsed.

The page-image items have no machine check of the value; those values rest on my reading of the rendered page:

- utilities-h106 and utilities-h111;
- tmsd-h107, tmsd-h109, tmsd-h111 and tmsd-h112.

Text and OCR were still run on these items. They match for utilities-h111, through the speaker notes.

Other checks:

- **Printed page:** it must equal the PDF label, or be a whole token in the page's first 12 or last 3 text lines. For
  the 5 image-only cases (010604 p286 and the four RDM sheets) it was read off the image, and the item records
  `printed_ok`.
- **Page rules:** no gold page is excluded, already used by the held-out set, or shared between two of these items.
- **Split:** every item is `locked`. Refusals hash on the question text.
- **Item types:**
  - correct items: the premise does not match the value or any accept string;
  - clarify items: 3 branches each;
  - list-over-page-break items: at least one part only on the first page and one only on the second.
- **Schema:** `validate_items` and `tag_errors` were run on a copy without `replaces` and returned no errors.

## Specs not matched exactly, and tag notes

- **wztc-h104 (revision_marks refusal).** wztc has no unused "Reserved" or "To Be Developed" section left: CFR 630's
  reserved subparts are already used, and the Guidelines placeholder belonged to the retired item. The new item asks
  for the person in a contacts entry printed as "(Vacant)". The right reply is that no one is named, and `accept_reply`
  is ["vacant"].
- **utilities-h107: multi_column dropped.** UAM p47 is single-column. My shingle scans found no unused two-column
  utilities page that shares real text with another division; only boilerplate was shared. The scans covered:
  - the CFR 645 and 710 pages;
  - 010604, EDC-8, hif22002, hif22040 and 09utilcoordcert.
- **tmsd-h112: not_first_row_col dropped.** The rotated near-identical page I found is a drawing (RDM F-4B, the twin
  of the Access manual's turn-lane exhibit), not a table. 04100 p47 (rotated Figure 18 bar chart) would have kept
  not_first_row_col, but it has no near-identical twin in tmsd.
- **Extra tags that apply but were left off, to keep each spec's tag set:**
  - tmsd-h107 is also `scan` and `near_identical` (sheet F-3A-3 on PDF p8 is the 20-foot-median twin);
  - utilities-h111 is also `printed_vs_pdf`;
  - several UAM, CFR and L18 pages also differ between printed and PDF page numbers.
- **Duplicate support pages outside the gold page:**
  - wztc-h107: TMP Design Manual p41 (excluded) repeats the Chapter 2.2 pointer for slopes.
  - utilities-h112: UAM p201 (Appendix C) states the same sheet sizes; the question names section 3.2.1.1.
  - tmsd-h107: the 4° skew note also appears on F-3A-3, but with 230′.
  - tmsd-h112: the near-identical drawing is Access p89, an excluded page.
- **Scorer fit:**
  - tmsd-h110 keeps bare numbers ("16.2") as values because the table cells carry no % sign; the % forms are in
    accept/all_of.
  - utilities-h106's OCR has a stray slash after the fraction, so only the image reading verifies it.
