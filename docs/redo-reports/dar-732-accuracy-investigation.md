# Where the wrong answers come from (DAR-732)

For Dr. Namian, Nov 17, 2026. Prepared from the held-out test run of the live site (the OpenAI model, Nov 16) after the scoring fix of the same day. No new questions were asked to write this; every reply below is one the live site already gave.

## The short version

- The test asked the live assistant **286 questions** it had never seen. **28 of 286** replies were scored "confident and wrong": an answer with a source, but not the right one.
- Read one by one, **12 of the 28 are not errors**. The reply was right and the automatic scoring missed it (mostly because the reply said the same thing in other words).
- That leaves **16 real problems in 286 replies (5.6%)**:
  - **6 gave a wrong number or reference (2.1% of 286).** 5 of those 6 come from pages that are pictures rather than text: a drawing, a scanned page, or a table printed sideways. The step that turns those pictures into text loses fractions ("2 ½" became "2 /2") and scrambles the order of table columns.
  - **7 were incomplete.** 5 of them are lists that continue onto the next page; the assistant only received the first page.
  - **3 handled "I don't know" wrongly**: 2 answered when the documents don't cover the question, 1 declined when they do.
- **Documents that disagree caused none of the 28.** One wrong answer (below, example 4) involves two NCDOT manuals that give different lengths for the same thing, but the cause there was that the right page never reached the assistant.

## 1. The 28, sorted by cause

| Cause | What it means | Count | Real problems among them |
|---|---|---|---|
| A. Never found it | The page with the answer (or the second half of it) never reached the assistant | 10 of 28 | 9 |
| B. Misread it | The right page was in front of the assistant; it still got the value wrong or left part out | 5 of 28 | 5 |
| C. Should have said "not covered" | The documents don't answer the question, and the reply was scored as an answer | 4 of 28 | 2 |
| D. The test was wrong | The reply was right; the scoring missed it | 9 of 28 | 0 |
| E. Documents disagree | Two documents gave different values and the assistant used the wrong one | 0 of 28 | 0 |
| **Total** | | **28** | **16** |

Two of the four in C are really correct: the reply opens "The UAM does not specify a daily per diem dollar amount" (utilities-h090) and "The documents don't state how many ... by the end of 2025" (wztc-h072). The scoring rule for refusals didn't recognise those wordings. One item in A (utilities-h080) is also right in substance: the UAM page never arrived, but the assistant gave the same formula from the FHWA guide and 23 CFR 645, which say the same thing.

How bad each of the 28 is:

| Verdict | Count |
|---|---|
| Wrong number, rule or reference a reader could act on | 6 of 28 |
| Incomplete: right as far as it goes, but missing list items or a case | 7 of 28 |
| Answered when it should have said "not covered", or the reverse | 3 of 28 |
| Not an error (right reply, scored wrong) | 12 of 28 |

## 2. What kind of page the problems sit on (causes A and B, 15 items)

| Page type | Count | Items |
|---|---|---|
| List or table that runs over a page break | 5 of 15 | utilities-h072, utilities-h073, utilities-h074, wztc-h032, wztc-h033 |
| Plain text | 4 of 15 | tmsd-h082, utilities-h058, utilities-h080, wztc-h086 |
| Map or drawing | 2 of 15 | tmsd-h009, tmsd-h049 |
| Rotated page (printed sideways) | 2 of 15 | tmsd-h019, tmsd-h052 |
| Scanned page or picture | 1 of 15 | utilities-h056 |
| Table | 1 of 15 | tmsd-h024 |

All five drawing, rotated and scanned pages have no text layer, so their text comes from character recognition (OCR). All five gave a wrong value. Seen from the whole test:

- Questions whose answer had to be read off a page image: **5 of 31 confident and wrong (16%)**, against **23 of 255 (9%)** for the rest.
- Questions about a list that runs over a page break: **8 of 15 confident and wrong (53%)**, against **20 of 271 (7%)** for the rest. 5 of the 8 are real (incomplete lists); 3 were right and scored wrong.

## 3. Worked examples

**1. A scanned page loses a fraction** (utilities-h056, scanned page, cause B)
- Question: In the Indiana cut road permit, what is the maximum variation from vertical allowed on the edge of a removed concrete pavement area?
- Assistant: "The maximum variation from vertical is 1/2 inch."
- Right answer: 1 ½ inches (UAM appendix, PDF page 278, printed page 262).
- Why: the page is a degraded scan. The text recognition read "1 ½" as "1/½2", and the assistant made "1/2" of it.

**2. A table printed sideways is read in the wrong column order** (tmsd-h052, rotated page, cause B)
- Question: In the Roadway Design Manual's Figure 4 (sheet F-4A), what bay taper length goes with a 55 mph design speed?
- Assistant: "200 feet."
- Right answer: 150 feet (Chapter 9, PDF page 13, sheet F-4A). 200 feet is the minimum deceleration length in the same row.
- Why: the sheet is printed sideways. After turning it, the text recognition gives each row right to left ("150' 500' 200' 50 55"), and the assistant picked the wrong column.

**3. A list that continues on the next page** (wztc-h033, list over a page break, cause A)
- Question: FHWA's work zone impacts assessment guide gives examples of overall policy issues an agency's work zone guidance can address. List them all.
- Assistant: five items, presented as the full list.
- Right answer: eight items, five on printed page 3-13 and three on 3-14 (significant-project criteria, exception criteria, training).
- Why: only page 3-13 reached the assistant. Today the search adds the following passage for the top two results only, and here that passage was still on page 3-13. In 2 of the 5 page-break cases the assistant did say the list looked cut off; in the other 3 it did not.

**4. The right page never arrived, and a backup model answered from another manual** (tmsd-h019, rotated scanned page, cause A)
- Question: In the street and driveway access policy, the "Recommended Treatment for Turn Lanes" exhibit: what desirable deceleration length goes with a 50 mph design speed?
- Assistant: "550 feet (this length includes the taper)", citing the Roadway Design Manual.
- Right answer: 300 feet (Policy on Street and Driveway Access, PDF page 88, printed page 78).
- Why: the exhibit is a sideways scan and never reached the assistant. The main model (OpenAI) declined; the free backup model then answered from the Roadway Design Manual's chapter 9 text, whose turn-lane table includes the taper (550 ft at 50 mph). This is the one case among the 28 where two NCDOT manuals give different numbers for the same speed, but the assistant never saw both side by side.

**5. A right answer the scoring counted as wrong** (tmsd-h016, cause D)
- Question: Can a two-way driveway meet the pavement edge at a 70-degree angle under the access policy?
- Assistant: "No. The access policy requires a two-way driveway's angle to the pavement edge to be between 75 and 90 degrees; 70 degrees is below the minimum."
- Right answer: no; the minimum is 75 degrees (Policy on Access, PDF page 61, printed page 51).
- Why counted wrong: the scoring looks for the words "75 degrees", and the reply says "75 and 90 degrees". Eight more of the 28 fail the same way.

## 4. Earlier cases from the other test set (Nov 16 investigation)

The same deployment was also run on the older test set (280 questions). Reading its 8 remaining wrong answers found the same kinds of cause:

| Question | What happened | Cause |
|---|---|---|
| tmsd-058 | 23 CFR 655 Table 1A: gave 45% (the maximum for other sheeting types) instead of 30% for yellow Type V | B, wrong table cell |
| utilities-008 | UAM Table 4-1: gave Use and Occupancy Agreement instead of Utility Construction Agreement (header spanning two columns) | B, wrong table cell |
| utilities-013 | Conduit size table: answered from the similar table on the next page (2.002 in instead of 1.913 in) | A, wrong page retrieved |
| wztc-075 | MUTCD buffer length at 50 mph: OpenAI declined, and the free backup model answered 240 ft from NCDOT's own buffer table (Chapter 2 and the Division 11 manual) instead of the MUTCD's 425 ft | A, plus two documents that disagree (NCDOT vs MUTCD) |
| wztc-047 | Mowing layout speed: the page was stored with strikethrough marks ("~~5~~ 5 MPH"), so the answer repeated that garbled text instead of saying 55 MPH | B, text conversion; fixed Nov 17 (PR #62: marks removed, index rebuilt) |
| wztc-096 | Expected "not covered", but the Standard Specifications (p.617) do say "100 mph wind load"; the assistant was right | D, the test item is wrong |

wztc-075 is the clearest "documents disagree" case seen so far: NCDOT's buffer-space table gives 240 ft at 50 mph, while the MUTCD table the question names gives 425 ft.

## 5. Answer to the hierarchy question

**How many wrong answers come from documents that disagree? None of the 28 (0 of 286 questions).** No reply picked the wrong value from two conflicting documents that were both in front of it.

Related, but not the cause:
- **4 of the 28** were answered from a different document than the one the question named, because the named one never reached the assistant (tmsd-h019, tmsd-h024, utilities-h080, wztc-h086). In 3 of the 4 the other document said the same thing; only tmsd-h019 gave a different number.
- The 11 test questions written specifically about conflicting documents all scored right (0 of 11 confident and wrong).
- On the older set, one case (wztc-075, NCDOT 240 ft vs MUTCD 425 ft) is a real disagreement between a state and a federal document. A hierarchy rule would decide which one to show first; today the assistant can't tell them apart.

So a document hierarchy (DAR-674) is worth having for the production version, but it would not have fixed any of these 28.

## 6. What this means for the fix

In order of how many real problems each would remove:

1. **Show the assistant the page picture for drawings, scans and sideways tables (DAR-733).** 5 of the 6 wrong numbers come from those pages, where turning the picture into text loses fractions and column order. Reading the image directly avoids that step.
2. **Bring along the next page when a list or table runs over a page break.** 5 of the 7 incomplete answers. Today the next passage is added only for the top two results, and it is often still on the same page. When a passage ends at the bottom of a page, the start of the next page should come with it.
3. **Stop the free backup model from answering after OpenAI declines, or accept its answer only when it cites the document the question names.** It handled 26 of the 286 questions; 3 of those 26 ended among the 28 (tmsd-h019 wrong value, tmsd-h082 incomplete, tmsd-h100 answered a "not covered" question), plus wztc-075 on the older set. This is the open PM decision (3) from Nov 16.
4. **Fix the scoring so the test measures what it should.** 11 of the 28 are right replies scored as wrong (9 reworded answers, 2 refusals in the model's own words). The real error rate is closer to 16 of 286 (5.6%) than 28 of 286 (9.8%), and future comparisons should use the fixed scoring.
5. **"Not covered" answers.** 2 replies answered questions the documents don't cover, both small: one gave a related rule without saying the asked one isn't there (tmsd-h100), one implied a placeholder section has content (wztc-h043).

## How this was done, and what to keep in mind

- Source: `docs/heldout-set/openai-site-main.json` (PR #60, scored again by PR #61 at 79d3c5f). Each of the 28 was read with its test item, the passages the search returned, the cited page and the indexed text of the gold page as it was at the run (index before the Nov 17 rebuild). One gold value read off a page image (tmsd-h049, 3:1) was checked against the page image again; the other four image-read gold values among the 28 match the recognised text. The remaining 26 image-read gold values were not rechecked.
- The per-item sorting, with a one-line reason for each, is in [`dar-732-buckets.json`](dar-732-buckets.json).
- Rule for A vs B: if any part of the answer was in a passage that never reached the assistant, it is A; if everything needed was in front of it, it is B. The "passages it saw" are the cited pages plus the search's top 5 on the local copy of the index; the site does not report the passages it sent.
- **Cost to the test set.** The held-out set's rules say an item whose failure is read in detail becomes a development item. These 28 were read for this report, so before the held-out set gives another clean before/after number, they should be replaced with fresh questions on other pages (or the next comparison should leave them out and say so).
