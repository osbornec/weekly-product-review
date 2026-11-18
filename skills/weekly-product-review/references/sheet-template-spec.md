# Google Sheet & Excel Template Specification (Swiss Precision Grid)

Canonical design system for all Weekly Product Review outputs: Google Sheets / `.xlsx`, Companion HTML & Google Docs, and preview assets.

## Design Tokens (Single Source of Truth)

### Typography
- **Google Sheet / `.xlsx`:** `Inter` 10pt (mapped natively via Google Fonts when imported into Google Sheets; clean sans fallback in offline Excel).
- **Companion HTML / Google Docs & Marketing Graphics:** `'Inter', system-ui, -apple-system, 'Segoe UI', Arial, sans-serif` (applied explicitly to Google Docs named styles and rendered directly with `Inter` in HTML and preview assets; no serif mix).
- **CLI & Code Snippets:** `Consolas`, `'SFMono-Regular'`, monospace.

### Color Palette
| Token | Hex | RGB | Usage |
| :--- | :--- | :--- | :--- |
| **Header Bar (Midnight)** | `#09090B` | `(9, 9, 11)` | Row 5 column headers (`Metric`, `Target`, week dates `mmm dd`), HTML table header, bold `#FAFAFA` ink |
| **Calendar Strip & Section Dividers (Cool Slate)** | `#F1F5F9` | `(241, 245, 249)` | Rows 1–4 calendar metadata (`#52525B` ink) and section banners (`#0F172A` bold ink) |
| **Manual Input (Ice Blue)** | `#EFF6FF` | `(239, 246, 255)` | Populated manual inputs (`type: manual`, `#1E3A8A` ink) |
| **Calculated / Automated (Zinc)** | `#FAFAFA` | `(250, 250, 250)` | Formula-driven metrics, automated collectors, active analysis rows (`#52525B` ink) |
| **Preview / Pending / N/A (Warm Amber)** | `#FFEDD5` | `(255, 237, 213)` | Explicit previews, pending metrics and `"N/A"` analysis cells (`#9A3412` ink) |
| **Canvas / Legend Strip** | `#F8FAFC` | `(248, 250, 252)` | HTML page backdrop, Row 6 legend bar (`#52525B` ink), hairline border `#E2E8F0` / accent `#94A3B8` |

In generated workbooks the legend merges A6:B6 inside the frozen columns and wraps at 36pt. Ordinary blank input cells use the neutral canvas fill. A populated preview takes the amber fill even for a metric normally entered manually.

---

## Workbook Tab Structure

For every calendar year present in `wpr/metrics-data.md` (or configured `Year`):
1. **Quarterly Tabs:** `Q1 <YY>`, `Q2 <YY>`, `Q3 <YY>`, `Q4 <YY>` (newest week on the left: `Col C` = newest week of quarter, rightmost column = Week 1 of quarter).
2. **Annual Tab:** `Full Year <YYYY>` (newest week on the left: `Col C` = Week 52/53, rightmost = Week 1).
3. **Active Tab Selection:** Sets `activeTab` and `tabSelected="1"` to the newest active quarter tab (e.g., `Q4 26`). When syncing to Google Sheets (which ignores Excel's `activeTab` property and opens tab 0), pass `--active-tab-first` to `build` so the current quarter appears first.

## Row Layout & Visual Hierarchy

| Row | Column A | Column B | Columns C..Rightmost | Style |
| :--- | :--- | :--- | :--- | :--- |
| **1** | `Quarter` | *(blank)* | `=ROUNDUP(MONTH(C4)/3, 0)` | Cool Slate `#F1F5F9`, `#52525B` ink, 18pt |
| **2** | `Week of Quarter` | *(blank)* | `=INT((C4-DATE(YEAR(C4),3*C1-2,1))/7)+1` | Cool Slate `#F1F5F9`, `#52525B` ink, 18pt |
| **3** | `Week of Year` | *(blank)* | `=WEEKNUM(C4)` | Cool Slate `#F1F5F9`, `#52525B` ink, 18pt |
| **4** | `Friday` *(or configured day)* | *(blank)* | Oldest col = start date; newer cols `=D4+7` | Cool Slate `#F1F5F9`, Date `yyyy-mm-dd`, 18pt |
| **5** | `Metric` | `Target` | `=C4` *(date only at close, date with “Preview” while open)* | Midnight `#09090B`, Bold `#FAFAFA`, 28pt, Frozen bottom |
| **6** | Wrapped two-line legend merged across A:B | *(merged)* | *(blank)* | `#F8FAFC`, `#52525B` ink, 36pt |
| **7** | `Coverage / Review Doc` | *(blank)* | One coverage cell per week with the date window, missing sources and a link to the existing Doc | Wrapped text |
| **8+** | **Section Header** | *(blank)* | *(blank)* | Cool Slate `#F1F5F9`, `#0F172A` Bold, 24pt |
| **9+** | Metric rows & Analysis sub-rows | Quarter-scoped target | Values / Formulas | Ice Blue / Zinc / Amber fills, `#E2E8F0` borders, conditional `"N/A"` -> Amber |
| **Bottom** | `Notes` | *(blank)* | Closed-week highlights | Cool Slate header + hairline cells |

These are generated workbook positions. For an existing live Sheet, locate the coverage and highlights rows by purpose, metric rows by ID, and the week column by its actual date. Preserve the calendar key and date formula. Write preview figures as literal text and keep comparison and cumulative cells blank. At close, restore the date-only number format and replace preview text with verified numbers or blanks. Coverage and the Doc link share one cell. Use a separate Notes row for closed-week highlights.

---

## Standard Formulas (Google Sheets + Excel Compatible)

- **WoW Change (`wow`)**:
  `=IF(COUNT(<current>,<prior>)<>2,"N/A",IFERROR(<current>/<prior>-1,"N/A"))`. The prior reference is exactly seven days earlier, including a prior quarter/year tab when needed. Missing or incompatible periods are unavailable; older observations are never substituted.
- **4-Week Avg (`rolling_4w`)**:
  `=IF(COUNT(<w0>,<w1>,<w2>,<w3>)<>4,"N/A",AVERAGE(<w0>,<w1>,<w2>,<w3>))`. References are consecutive weekly dates, crossing a quarter/year boundary when necessary. Four closed comparable numeric periods are required, including valid zero. Preview/stale/unavailable values are excluded. Rebuild after closing a period or changing its comparison group.
- **QTD Total / YTD Total (`qtd_sum`)**:
  `=IF(ISNUMBER(<c><r>),SUM(<c><r>:$<oldest_col><r>),"")`
- **Carryover Cumulative Metric (`cumsum:<id>`)**:
  On `Q1` (first year): `=IF(ISNUMBER(<c><sr>),SUM(<c><sr>:$<oldest><sr>),"")`. On later quarters or years, add prior tab totals inside the numeric guard so cumulative totals carry across boundaries.
- **Target Delta (`vs_target`)**:
  `=IF(OR(ISBLANK(<c><r>),ISBLANK($B<r>)),"",IFERROR(<c><r>/$B<r>-1,"N/A"))`
- **QoQ Delta (`vs_prior_q`)**:
  Aligned by **Week-of-Quarter offset from the oldest (rightmost) column**, comparing Week `w` in the current quarter to Week `w` in `<prev_q>` even when quarters differ in week count.
- **YoY Delta (`yoy`)**:
  Compares Week `w` on `<Q_or_FY_tab>` against the matching week on the prior year's tab (`=IF(OR(ISBLANK(<c><r>),ISBLANK('<prev_yr_tab>'!<prev_c><r>)),"",IFERROR(<c><r>/'<prev_yr_tab>'!<prev_c><r>-1,"N/A"))`, or Amber `"N/A"` when no prior year exists).

Each row-4 date formula includes its numeric serial cache. A hidden final `Metric ID` column stores stable metric identities for imports. Neither its presence nor `--active-tab-first` changes the calendar date-column map.
