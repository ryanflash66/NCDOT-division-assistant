# Page images to the model: the measurement (DAR-733)

Nov 17, 2026. One held-out run with page images on, against a run of the same code with them off, made the same night on the same 286 locked questions.

## Short version

- **Page images did not lower confident wrong answers or raise value right**, so `PAGE_IMAGES_TO_MODEL` stays **off** (the ticket's rule: on by default only if confident wrong goes down and value right goes up).
- They did fix the 3 scanned or sideways pages DAR-732 traced to a misread value (tmsd-h009, tmsd-h019, tmsd-h052). Three other questions got worse, so the totals did not move.
- They cost more than estimated: about **+80% a question** (estimate: +21%). Answers took 1.7 s longer on average.

## The runs

| | Images off (control) | Images on |
|---|---|---|
| Label | `openai-site-dar735` | `openai-site-dar733-images` |
| Where | live site (main with PR #66) | CLI preview of PR #67 with `RENDER_PAGES=1`, `PAGE_IMAGES_TO_MODEL=on` (cap 4, detail `auto`) |
| Questions | the 286 locked held-out items as of Nov 16 (before DAR-737's swap), so they compare item by item with `openai-site-main` | same |
| Scorer | DAR-737 | DAR-737 |
| Answered by | gpt-6.1-terra, 286/286 | gpt-6.1-terra, 286/286 |
| Errors | 0 | 0 |

## Results (95% Wilson intervals)

| | Images off | Images on |
|---|---|---|
| Confident wrong | 16/286 (3-9%) | 17/286 (4-9%) |
| Value right | 222/242 (88-95%) | 222/242 (88-95%) |
| Strict (value and cited page) | 202/242 (78-88%) | 199/242 (77-87%) |
| Cited page right | 223/251 (84-92%) | 219/252 (82-91%) |
| Answerable declined | 6/256 (1-5%) | 6/256 (1-5%) |
| Must-refuse answered | 1/30 (1-17%) | 2/30 (2-21%) |
| Clarify right | 12/14 | 13/14 |

Item by item:

- **Became right with images:** tmsd-h009, tmsd-h019 and tmsd-h052, the scanned and sideways pages DAR-732 found misread.
- **Stopped being confident wrong:** those 3, plus tmsd-h024.
- **Became confident wrong:** utilities-h058, utilities-h066, utilities-h078, wztc-h043 and wztc-h079.
- **Value lost:** utilities-h058, utilities-h066 and wztc-h079.

The run's answers are not deterministic: the control itself differs from the Nov 16 run by a similar handful of items in each direction. So only the three fixed scan pages look like a real effect of the images.

### By kind of page

77 items carry a scan, sideways, figure, symbol or table-layout tag:

| | Images off | Images on |
|---|---|---|
| Confident wrong, those 77 | 5 | 4 |
| Value right, those 77 | 66/74 | 68/74 |
| Confident wrong, the other 209 | 11 | 13 |
| Value right, the other 209 | 156/168 | 154/168 |

The small gain sits where the images were meant to help. The other questions lost a little, which fits run-to-run noise but could also be the images distracting the model on text pages. This run cannot tell the two apart.

## Cost and time

The function logs every OpenAI call (`openai_spend`, `page images: N of M sent`). The last 49 questions of each run are still in the deployments' logs:

| Last 49 questions | Images off | Images on |
|---|---|---|
| OpenAI cost | $0.212 | $0.389 |
| Cost a question | $0.0043 | $0.0079 |
| Input tokens a call (mean) | 3,500 | 6,655 |
| Images a call (when any) | | 2.9 |

Across both whole runs, the shared monthly ledger went from $1.82 to $4.02 ($2.20, including a few test questions). Split in the same ratio, that is about **$0.77 for the control run and $1.40 for the images run**: about $0.0027 and $0.0049 a question, **+80%**.

The estimate (`dar-733-cost-estimate.md`) assumed 404 tokens an image. The logs show about 1,300 extra input tokens per image sent, three times that. gpt-6.1-terra seems to bill a 510 x 660 page at `detail: auto` well above the vision guide's patch count. `PAGE_IMAGES_DETAIL=low` would cut that, at the cost of blurring the small print the images were meant for.

Time: the mean answer took 8.5 s with images against 6.8 s without; the slowest 10% took 10.7 s against 9.0 s; the slowest answer took 15.5 s. All are well inside the 55 s budget.

## Found on the way

- **The bundle limit.** A `RENDER_PAGES=1` build could never deploy: `includeFiles: public/**` pulled the 247.5 MB of rendered pages into the function (547 MB against Vercel's 500 MB limit). PR #67 now includes only `public/{*,assets/**}`; the live page and its assets load with it.
- **Preview access.** A preview can only be measured with the project's Protection Bypass for Automation. It was turned on for this run and revoked after it. The runner sends the secret when `VERCEL_AUTOMATION_BYPASS_SECRET` is set.

## What would be worth trying

- Images only for scanned and sideways pages, not tables, figures or captions: the 3 fixes are all scans or sideways pages, and it would roughly halve the images.
- Measure that on the new held-out set (after DAR-737), with a repeat of the control to size the noise.
