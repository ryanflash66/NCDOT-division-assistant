# Multi-page table merge: check of the rule (DAR-655)

`rag/table_merge.py` joins a table that runs over a page break into one table before chunking. This page scores the rule on the corpus audit's candidate breaks.

**Candidates.** A candidate is a pair of pages where the audit (`.handoff/redo-nov4/corpus-audit.json`) found a `find_tables` box ending in the bottom 10% of page N (`tabbot`) and one starting in the top 12% of page N+1 (`tabtop`): 166 breaks in 15 of the 60 documents. Most come from two documents: the Traffic Services Legal Guide (76; it is one table over 706 pages) and Division 11 Combined (55; standard drawings, where the title block is a ruled box at the bottom of every sheet).

**How it was run.** `py -m prototype.table_merge_check --out <file>` reads each candidate's document with the build's reader (`rag.loader`, with table boxes from pymupdf-layout) and applies `merge_decisions`. To keep the run short it reads only the pages within 3 of a candidate, not whole documents (the Standard Specifications have 857 pages), so running heads and footers are learned from that window. The build itself reads the whole document.

**The rule.** Page N must end with a table (only page numbers or running heads/footers after it) and page N+1 must start with one (only page furniture, a "continued" caption or page N's caption again before it). The two tables must have the same column count; one column fewer on page N+1 is allowed only under a "continued" caption, since pymupdf4llm drops a column that is empty on the whole page. Then at least one signal must hold: page N+1 repeats page N's header row, a caption says "continued" / "(cont." / "- continued" / "Sheet 2 of 4", or the table boxes reach the bottom 15% of page N and the top 12% of page N+1.

## Result on the 20 hand-checked breaks

I picked the 20 to cover every document with candidates (except two with a single "page does not end with a table" candidate) and both outcomes, then opened each break in the PDF and decided whether page N+1 continues page N's table. 15 are continuations and 5 are not.

| rule version | true merges | wrong merges | missed | correctly kept apart | precision | recall |
|---|---|---|---|---|---|---|
| first version (as the previous worker left it) | 7 | 0 | 8 | 5 | 1.00 | 0.47 |
| tuned (committed) | 12 | 0 | 3 | 5 | 1.00 | 0.80 |

**These thresholds and rules were tuned on these same 20 breaks, so the tuned numbers are optimistic.** No separate held-out set was scored. What changed, and the break that motivated each change:

- A page that holds nothing but the table and its footer ("Page 18 of 706") lets the joined table carry on to the next page. Before, the footer became a Document of its own and stopped the chain (Legal Guide p.18).
- Edge lines are measured without Markdown, so `# **Establishing Operational Objectives**` counts as a short running head (Signal System Timing manual p.16).
- Page N's caption printed again above the continuation is matched by its table label ("Table 6H-1"), and "(Sheet 2 of 4)" and "- continued" at the end of a caption count as continued markers (part6 p.40, Chapter 2C p.7, interim pilot program p.19).
- The bottom band is 15%, not the audit's 10%. pymupdf-layout's table box stops at the last row's text above a running footer, so the Legal Guide's full-page tables end at 0.886 to 0.91 of the page height.
- From code review, not the 20: one column fewer now needs a "continued" caption. Boxes at the page edges are not enough, because a new, narrower table at the top of the next page fits them too. Short prose lines above a continuation are kept rather than dropped.

The 3 misses are all column-count mismatches: the Legal Guide's empty columns come and go page by page (9 vs 7 columns on pp.1-2), the C34 manual's p.59 table is garbled in extraction, and the WZ Safety guidelines' p.15 table gains a column. Merging those would mean guessing which column is missing, which puts values under the wrong header.

## Result on all 166 candidates

The rule merges 53 of the 166:

| decision | breaks |
|---|---|
| merge on geometry alone | 39 |
| merge with a repeated header (with or without other signals) | 13 |
| merge on a continued caption | 1 |
| keep apart: page N does not end with a table | 61 (53 of them Division 11 drawing sheets) |
| keep apart: column counts differ | 48 (44 in the Legal Guide) |
| keep apart: page N+1 starts with prose | 4 |

The Legal Guide accounts for most of what is left: 32 of its 76 breaks merge, and the other 44 all have column counts that differ, mostly by one. Of the 18 candidates whose next page mentions "continued" anywhere, 8 merge.

**Chunks and citations.** A merged table can span many pages (the Legal Guide's runs go on for dozens), so each chunk cut from it gets its own `page` and `page_end` from the rows it actually holds: every line is looked up on the original pages (`rag.table_merge.page_span`). A Legal Guide row from page 300 then cites page 300, not the page where the joined table starts. The hosted app's `retrieval.as_passages` and `answer.narrow` take the largest `page_end` of a passage's parts.

## The 20 hand-checked breaks

| # | document | pages | hand check: same table? | rule | reason | note |
|---|---|---|---|---|---|---|
| 1 | tmsd/C34 - Manual 2012.pdf | 52–53 | yes | merge | header + geometry | Form-field table (Section / Enter), header reprinted on p.53 |
| 2 | tmsd/C34 - Manual 2012.pdf | 58–59 | yes | keep apart | column count 2 vs 3 | Vehicle style code list runs on (30 Military / 31 Police); p.59 extraction garbled |
| 3 | tmsd/Chapter2c.pdf | 6–7 | yes | merge | continued + geometry | Table 2C-1 Sheet 3 of 4 to Sheet 4 of 4 |
| 4 | tmsd/L18_TSLG_Guide.pdf | 1–2 | yes | keep apart | column count 9 vs 7 | Legal Guide: one table over 706 pages |
| 5 | tmsd/L18_TSLG_Guide.pdf | 16–17 | yes | merge | geometry | Legal Guide: one table over 706 pages |
| 6 | tmsd/L18_TSLG_Guide.pdf | 18–19 | yes | merge | geometry | Legal Guide: one table over 706 pages |
| 7 | tmsd/interim-design-safety-pilot-program.pdf | 18–19 | yes | merge | header + continued | Candidate locations table, p.19 says "- continued" |
| 8 | utilities/DOT Encroachment Submissions User Manual - July 2023.pdf | 26–27 | yes | merge | geometry | Review-type definition table continues |
| 9 | utilities/NCDOT Utility Cost Reimbursement Guidance_8-20-2026.pdf | 3–4 | yes | merge | geometry | Property-interest table; a cell's text runs over the break |
| 10 | utilities/fhwahop09021.pdf | 94–95 | yes | merge | header | Cost table, header reprinted |
| 11 | tmsd/Signal System Timing Philosophy Manual.pdf | 15–16 | yes | merge | header + geometry | Operational objectives table, header reprinted |
| 12 | wztc/part6.pdf | 39–40 | yes | merge | header + geometry | Table 6H-1 caption and header reprinted on p.40 |
| 13 | wztc/WZSafetyAndMobilityGuidelines.pdf | 8–9 | yes | merge | geometry | Goals / owners action table continues |
| 14 | wztc/WZSafetyAndMobilityGuidelines.pdf | 14–15 | yes | keep apart | column count 3 vs 4 | Goals / owners action table continues |
| 15 | wztc/fhwahop12005.pdf | 101–102 | yes | merge | geometry | Alternative evaluation table; row 5 split by the break |
| 16 | wztc/2024 Standard Specifications for Roads and Structures.pdf | 580–581 | no | keep apart | column count 16 vs 8 | Table 1080-1 then a different Table 1080-2 |
| 17 | wztc/Division 11 Combined.pdf | 1–2 | no | keep apart | page does not end with a table | Standard drawing sheets (title blocks), no table runs over |
| 18 | wztc/Division 11 Combined.pdf | 25–26 | no | keep apart | page does not end with a table | Standard drawing sheets (title blocks), no table runs over |
| 19 | wztc/fhwahop12005.pdf | 130–131 | no | keep apart | next page starts with prose | Data table ends; p.131 starts with prose and a chart |
| 20 | wztc/fhwahop12005.pdf | 148–149 | no | keep apart | next page starts with prose | Lane-closure schedule ends; p.149 starts Table 62 |

## All 166 candidate breaks

`audit cont` marks breaks where the audit found "continued" or "(cont" anywhere on page N+1.

| # | document | pages | audit `cont` | rule | reason |
|---|---|---|---|---|---|
| 1 | tmsd/C34 - Manual 2012.pdf | 41–42 |  | merge | header + geometry |
| 2 | tmsd/C34 - Manual 2012.pdf | 45–46 |  | merge | header + geometry |
| 3 | tmsd/C34 - Manual 2012.pdf | 52–53 |  | merge | header + geometry |
| 4 | tmsd/C34 - Manual 2012.pdf | 56–57 |  | merge | header + geometry |
| 5 | tmsd/C34 - Manual 2012.pdf | 58–59 |  | keep apart | column count 2 vs 3 |
| 6 | tmsd/C34 - Manual 2012.pdf | 61–62 |  | merge | header + geometry |
| 7 | tmsd/Chapter2c.pdf | 4–5 |  | merge | header + continued + geometry |
| 8 | tmsd/Chapter2c.pdf | 5–6 |  | merge | header + continued + geometry |
| 9 | tmsd/Chapter2c.pdf | 6–7 |  | merge | continued + geometry |
| 10 | tmsd/L18_TSLG_Guide.pdf | 1–2 |  | keep apart | column count 9 vs 7 |
| 11 | tmsd/L18_TSLG_Guide.pdf | 2–3 |  | keep apart | column count 7 vs 8 |
| 12 | tmsd/L18_TSLG_Guide.pdf | 5–6 |  | keep apart | column count 6 vs 7 |
| 13 | tmsd/L18_TSLG_Guide.pdf | 7–8 | yes | merge | geometry |
| 14 | tmsd/L18_TSLG_Guide.pdf | 9–10 | yes | keep apart | column count 6 vs 5 without a continued caption |
| 15 | tmsd/L18_TSLG_Guide.pdf | 16–17 |  | merge | geometry |
| 16 | tmsd/L18_TSLG_Guide.pdf | 17–18 |  | merge | geometry |
| 17 | tmsd/L18_TSLG_Guide.pdf | 18–19 | yes | merge | geometry |
| 18 | tmsd/L18_TSLG_Guide.pdf | 21–22 |  | keep apart | column count 5 vs 6 |
| 19 | tmsd/L18_TSLG_Guide.pdf | 29–30 | yes | keep apart | column count 5 vs 6 |
| 20 | tmsd/L18_TSLG_Guide.pdf | 35–36 |  | keep apart | column count 6 vs 5 without a continued caption |
| 21 | tmsd/L18_TSLG_Guide.pdf | 40–41 |  | keep apart | column count 6 vs 7 |
| 22 | tmsd/L18_TSLG_Guide.pdf | 46–47 |  | merge | geometry |
| 23 | tmsd/L18_TSLG_Guide.pdf | 47–48 | yes | keep apart | column count 6 vs 7 |
| 24 | tmsd/L18_TSLG_Guide.pdf | 49–50 | yes | merge | geometry |
| 25 | tmsd/L18_TSLG_Guide.pdf | 51–52 | yes | merge | geometry |
| 26 | tmsd/L18_TSLG_Guide.pdf | 56–57 |  | merge | geometry |
| 27 | tmsd/L18_TSLG_Guide.pdf | 57–58 |  | merge | geometry |
| 28 | tmsd/L18_TSLG_Guide.pdf | 62–63 |  | merge | geometry |
| 29 | tmsd/L18_TSLG_Guide.pdf | 65–66 |  | keep apart | column count 6 vs 7 |
| 30 | tmsd/L18_TSLG_Guide.pdf | 71–72 |  | merge | geometry |
| 31 | tmsd/L18_TSLG_Guide.pdf | 73–74 | yes | keep apart | column count 6 vs 5 without a continued caption |
| 32 | tmsd/L18_TSLG_Guide.pdf | 74–75 | yes | keep apart | column count 5 vs 4 without a continued caption |
| 33 | tmsd/L18_TSLG_Guide.pdf | 77–78 |  | merge | geometry |
| 34 | tmsd/L18_TSLG_Guide.pdf | 78–79 |  | merge | geometry |
| 35 | tmsd/L18_TSLG_Guide.pdf | 79–80 |  | keep apart | column count 5 vs 6 |
| 36 | tmsd/L18_TSLG_Guide.pdf | 80–81 | yes | merge | geometry |
| 37 | tmsd/L18_TSLG_Guide.pdf | 81–82 |  | merge | geometry |
| 38 | tmsd/L18_TSLG_Guide.pdf | 83–84 | yes | keep apart | column count 5 vs 6 |
| 39 | tmsd/L18_TSLG_Guide.pdf | 84–85 |  | keep apart | column count 6 vs 5 without a continued caption |
| 40 | tmsd/L18_TSLG_Guide.pdf | 87–88 |  | keep apart | column count 4 vs 5 |
| 41 | tmsd/L18_TSLG_Guide.pdf | 89–90 |  | keep apart | column count 6 vs 7 |
| 42 | tmsd/L18_TSLG_Guide.pdf | 94–95 | yes | keep apart | column count 4 vs 5 |
| 43 | tmsd/L18_TSLG_Guide.pdf | 99–100 |  | merge | geometry |
| 44 | tmsd/L18_TSLG_Guide.pdf | 100–101 |  | keep apart | column count 5 vs 4 without a continued caption |
| 45 | tmsd/L18_TSLG_Guide.pdf | 105–106 |  | keep apart | column count 7 vs 5 |
| 46 | tmsd/L18_TSLG_Guide.pdf | 107–108 |  | keep apart | column count 6 vs 7 |
| 47 | tmsd/L18_TSLG_Guide.pdf | 110–111 |  | merge | geometry |
| 48 | tmsd/L18_TSLG_Guide.pdf | 111–112 |  | keep apart | column count 5 vs 6 |
| 49 | tmsd/L18_TSLG_Guide.pdf | 114–115 |  | keep apart | column count 5 vs 7 |
| 50 | tmsd/L18_TSLG_Guide.pdf | 115–116 |  | merge | geometry |
| 51 | tmsd/L18_TSLG_Guide.pdf | 116–117 |  | merge | geometry |
| 52 | tmsd/L18_TSLG_Guide.pdf | 118–119 |  | merge | geometry |
| 53 | tmsd/L18_TSLG_Guide.pdf | 128–129 |  | keep apart | column count 5 vs 6 |
| 54 | tmsd/L18_TSLG_Guide.pdf | 133–134 |  | keep apart | column count 6 vs 7 |
| 55 | tmsd/L18_TSLG_Guide.pdf | 135–136 |  | merge | geometry |
| 56 | tmsd/L18_TSLG_Guide.pdf | 137–138 |  | keep apart | column count 7 vs 8 |
| 57 | tmsd/L18_TSLG_Guide.pdf | 147–148 | yes | keep apart | column count 5 vs 7 |
| 58 | tmsd/L18_TSLG_Guide.pdf | 148–149 |  | merge | geometry |
| 59 | tmsd/L18_TSLG_Guide.pdf | 149–150 |  | keep apart | column count 7 vs 6 without a continued caption |
| 60 | tmsd/L18_TSLG_Guide.pdf | 153–154 |  | merge | geometry |
| 61 | tmsd/L18_TSLG_Guide.pdf | 156–157 |  | merge | geometry |
| 62 | tmsd/L18_TSLG_Guide.pdf | 159–160 |  | keep apart | column count 6 vs 5 without a continued caption |
| 63 | tmsd/L18_TSLG_Guide.pdf | 161–162 |  | keep apart | column count 6 vs 5 without a continued caption |
| 64 | tmsd/L18_TSLG_Guide.pdf | 162–163 |  | keep apart | column count 5 vs 7 |
| 65 | tmsd/L18_TSLG_Guide.pdf | 164–165 |  | keep apart | column count 7 vs 6 without a continued caption |
| 66 | tmsd/L18_TSLG_Guide.pdf | 166–167 |  | merge | geometry |
| 67 | tmsd/L18_TSLG_Guide.pdf | 167–168 | yes | merge | geometry |
| 68 | tmsd/L18_TSLG_Guide.pdf | 176–177 |  | keep apart | column count 8 vs 7 without a continued caption |
| 69 | tmsd/L18_TSLG_Guide.pdf | 177–178 |  | merge | geometry |
| 70 | tmsd/L18_TSLG_Guide.pdf | 179–180 |  | merge | geometry |
| 71 | tmsd/L18_TSLG_Guide.pdf | 181–182 |  | merge | geometry |
| 72 | tmsd/L18_TSLG_Guide.pdf | 190–191 |  | keep apart | column count 7 vs 5 |
| 73 | tmsd/L18_TSLG_Guide.pdf | 193–194 | yes | keep apart | column count 6 vs 7 |
| 74 | tmsd/L18_TSLG_Guide.pdf | 195–196 |  | keep apart | column count 7 vs 6 without a continued caption |
| 75 | tmsd/L18_TSLG_Guide.pdf | 197–198 |  | merge | geometry |
| 76 | tmsd/L18_TSLG_Guide.pdf | 198–199 |  | keep apart | column count 7 vs 5 |
| 77 | tmsd/L18_TSLG_Guide.pdf | 201–202 |  | keep apart | column count 6 vs 7 |
| 78 | tmsd/L18_TSLG_Guide.pdf | 205–206 | yes | keep apart | column count 6 vs 9 |
| 79 | tmsd/L18_TSLG_Guide.pdf | 206–207 |  | keep apart | column count 9 vs 6 |
| 80 | tmsd/L18_TSLG_Guide.pdf | 207–208 |  | merge | geometry |
| 81 | tmsd/L18_TSLG_Guide.pdf | 210–211 |  | merge | geometry |
| 82 | tmsd/L18_TSLG_Guide.pdf | 211–212 |  | keep apart | column count 6 vs 5 without a continued caption |
| 83 | tmsd/L18_TSLG_Guide.pdf | 216–217 |  | keep apart | column count 5 vs 6 |
| 84 | tmsd/L18_TSLG_Guide.pdf | 219–220 |  | keep apart | column count 4 vs 7 |
| 85 | tmsd/L18_TSLG_Guide.pdf | 220–221 |  | keep apart | column count 7 vs 6 without a continued caption |
| 86 | tmsd/Signal System Timing Philosophy Manual.pdf | 15–16 |  | merge | header + geometry |
| 87 | tmsd/interim-design-safety-pilot-program.pdf | 17–18 |  | keep apart | page does not end with a table |
| 88 | tmsd/interim-design-safety-pilot-program.pdf | 18–19 | yes | merge | header + continued |
| 89 | tmsd/part3.pdf | 13–14 |  | keep apart | page does not end with a table |
| 90 | utilities/DOT Encroachment Submissions User Manual - July 2023.pdf | 26–27 |  | merge | geometry |
| 91 | utilities/DOT Encroachment Submissions User Manual - July 2023.pdf | 39–40 |  | merge | geometry |
| 92 | utilities/DOT Encroachment Submissions User Manual - July 2023.pdf | 50–51 |  | merge | geometry |
| 93 | utilities/NCDOT Utility Cost Reimbursement Guidance_8-20-2026.pdf | 3–4 |  | merge | geometry |
| 94 | utilities/fhwahop09021.pdf | 23–24 |  | merge | header + geometry |
| 95 | utilities/fhwahop09021.pdf | 94–95 |  | merge | header |
| 96 | wztc/2024 Standard Specifications for Roads and Structures.pdf | 580–581 |  | keep apart | column count 16 vs 8 |
| 97 | wztc/2024 Standard Specifications for Roads and Structures.pdf | 581–582 |  | keep apart | column count 8 vs 16 |
| 98 | wztc/Chapter_2.pdf | 13–14 |  | keep apart | page does not end with a table |
| 99 | wztc/Division 11 Combined.pdf | 1–2 |  | keep apart | page does not end with a table |
| 100 | wztc/Division 11 Combined.pdf | 2–3 |  | keep apart | page does not end with a table |
| 101 | wztc/Division 11 Combined.pdf | 3–4 |  | keep apart | page does not end with a table |
| 102 | wztc/Division 11 Combined.pdf | 4–5 |  | keep apart | page does not end with a table |
| 103 | wztc/Division 11 Combined.pdf | 5–6 |  | keep apart | page does not end with a table |
| 104 | wztc/Division 11 Combined.pdf | 6–7 |  | keep apart | page does not end with a table |
| 105 | wztc/Division 11 Combined.pdf | 7–8 |  | keep apart | page does not end with a table |
| 106 | wztc/Division 11 Combined.pdf | 8–9 |  | keep apart | page does not end with a table |
| 107 | wztc/Division 11 Combined.pdf | 9–10 |  | keep apart | page does not end with a table |
| 108 | wztc/Division 11 Combined.pdf | 10–11 |  | keep apart | page does not end with a table |
| 109 | wztc/Division 11 Combined.pdf | 11–12 |  | keep apart | page does not end with a table |
| 110 | wztc/Division 11 Combined.pdf | 12–13 |  | keep apart | page does not end with a table |
| 111 | wztc/Division 11 Combined.pdf | 13–14 |  | keep apart | page does not end with a table |
| 112 | wztc/Division 11 Combined.pdf | 14–15 |  | keep apart | page does not end with a table |
| 113 | wztc/Division 11 Combined.pdf | 15–16 |  | keep apart | page does not end with a table |
| 114 | wztc/Division 11 Combined.pdf | 19–20 |  | keep apart | page does not end with a table |
| 115 | wztc/Division 11 Combined.pdf | 20–21 |  | keep apart | page does not end with a table |
| 116 | wztc/Division 11 Combined.pdf | 21–22 |  | keep apart | page does not end with a table |
| 117 | wztc/Division 11 Combined.pdf | 22–23 |  | keep apart | page does not end with a table |
| 118 | wztc/Division 11 Combined.pdf | 23–24 |  | keep apart | page does not end with a table |
| 119 | wztc/Division 11 Combined.pdf | 24–25 |  | keep apart | page does not end with a table |
| 120 | wztc/Division 11 Combined.pdf | 25–26 |  | keep apart | page does not end with a table |
| 121 | wztc/Division 11 Combined.pdf | 26–27 |  | keep apart | page does not end with a table |
| 122 | wztc/Division 11 Combined.pdf | 27–28 |  | keep apart | page does not end with a table |
| 123 | wztc/Division 11 Combined.pdf | 28–29 |  | keep apart | page does not end with a table |
| 124 | wztc/Division 11 Combined.pdf | 29–30 |  | keep apart | page does not end with a table |
| 125 | wztc/Division 11 Combined.pdf | 30–31 |  | keep apart | page does not end with a table |
| 126 | wztc/Division 11 Combined.pdf | 31–32 |  | keep apart | page does not end with a table |
| 127 | wztc/Division 11 Combined.pdf | 32–33 |  | keep apart | page does not end with a table |
| 128 | wztc/Division 11 Combined.pdf | 33–34 |  | keep apart | page does not end with a table |
| 129 | wztc/Division 11 Combined.pdf | 34–35 |  | keep apart | page does not end with a table |
| 130 | wztc/Division 11 Combined.pdf | 35–36 |  | keep apart | page does not end with a table |
| 131 | wztc/Division 11 Combined.pdf | 36–37 |  | keep apart | page does not end with a table |
| 132 | wztc/Division 11 Combined.pdf | 37–38 |  | keep apart | page does not end with a table |
| 133 | wztc/Division 11 Combined.pdf | 38–39 |  | keep apart | page does not end with a table |
| 134 | wztc/Division 11 Combined.pdf | 39–40 |  | keep apart | page does not end with a table |
| 135 | wztc/Division 11 Combined.pdf | 40–41 |  | keep apart | page does not end with a table |
| 136 | wztc/Division 11 Combined.pdf | 41–42 |  | keep apart | page does not end with a table |
| 137 | wztc/Division 11 Combined.pdf | 42–43 |  | keep apart | page does not end with a table |
| 138 | wztc/Division 11 Combined.pdf | 43–44 |  | keep apart | page does not end with a table |
| 139 | wztc/Division 11 Combined.pdf | 44–45 |  | keep apart | page does not end with a table |
| 140 | wztc/Division 11 Combined.pdf | 45–46 |  | keep apart | page does not end with a table |
| 141 | wztc/Division 11 Combined.pdf | 46–47 |  | keep apart | page does not end with a table |
| 142 | wztc/Division 11 Combined.pdf | 47–48 |  | keep apart | page does not end with a table |
| 143 | wztc/Division 11 Combined.pdf | 48–49 |  | keep apart | next page starts with prose |
| 144 | wztc/Division 11 Combined.pdf | 49–50 |  | keep apart | page does not end with a table |
| 145 | wztc/Division 11 Combined.pdf | 50–51 |  | keep apart | page does not end with a table |
| 146 | wztc/Division 11 Combined.pdf | 51–52 |  | keep apart | next page starts with prose |
| 147 | wztc/Division 11 Combined.pdf | 52–53 |  | keep apart | page does not end with a table |
| 148 | wztc/Division 11 Combined.pdf | 53–54 |  | keep apart | page does not end with a table |
| 149 | wztc/Division 11 Combined.pdf | 54–55 |  | keep apart | page does not end with a table |
| 150 | wztc/Division 11 Combined.pdf | 55–56 |  | keep apart | page does not end with a table |
| 151 | wztc/Division 11 Combined.pdf | 56–57 |  | keep apart | page does not end with a table |
| 152 | wztc/Division 11 Combined.pdf | 57–58 |  | keep apart | page does not end with a table |
| 153 | wztc/Division 11 Combined.pdf | 58–59 |  | keep apart | page does not end with a table |
| 154 | wztc/WZSafetyAndMobilityGuidelines.pdf | 8–9 | yes | merge | geometry |
| 155 | wztc/WZSafetyAndMobilityGuidelines.pdf | 10–11 |  | merge | geometry |
| 156 | wztc/WZSafetyAndMobilityGuidelines.pdf | 14–15 |  | keep apart | column count 3 vs 4 |
| 157 | wztc/WZSafetyAndMobilityGuidelines.pdf | 15–16 |  | merge | header + geometry |
| 158 | wztc/fhwahop12005.pdf | 21–22 |  | keep apart | page does not end with a table |
| 159 | wztc/fhwahop12005.pdf | 36–37 |  | keep apart | page does not end with a table |
| 160 | wztc/fhwahop12005.pdf | 54–55 |  | keep apart | page does not end with a table |
| 161 | wztc/fhwahop12005.pdf | 55–56 |  | keep apart | page does not end with a table |
| 162 | wztc/fhwahop12005.pdf | 101–102 |  | merge | geometry |
| 163 | wztc/fhwahop12005.pdf | 126–127 |  | keep apart | page does not end with a table |
| 164 | wztc/fhwahop12005.pdf | 130–131 |  | keep apart | next page starts with prose |
| 165 | wztc/fhwahop12005.pdf | 148–149 |  | keep apart | next page starts with prose |
| 166 | wztc/part6.pdf | 39–40 |  | merge | header + geometry |
