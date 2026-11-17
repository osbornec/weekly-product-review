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
| **Manual Input (Ice Blue)** | `#EFF6FF` | `(239, 246, 255)` | Weekly manual inputs (`type: manual`, `#1E3A8A` ink) |
| **Calculated / Automated (Zinc)** | `#FAFAFA` | `(250, 250, 250)` | Formula-driven metrics, automated collectors, active analysis rows (`#52525B` ink) |
| **Pending / N/A (Warm Amber)** | `#FFEDD5` | `(255, 237, 213)` | Uninstrumented metrics (`ETA: <date>`) and `"N/A"` analysis cells (`#9A3412` ink) |
| **Canvas / Legend Strip** | `#F8FAFC` | `(248, 250, 252)` | HTML page backdrop, Row 6 legend bar (`#52525B` ink), hairline border `#E2E8F0` / accent `#94A3B8` |

Legend text in Row 6:
`Ice Blue = manual input | Zinc = calculated or automated | Amber = not yet instrumented or N/A`

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
| **5** | `Metric` | `Target` | `=C4` *(formatted `mmm dd`)* | Midnight `#09090B`, Bold `#FAFAFA`, 28pt, Frozen bottom |
| **6** | `Legend` | *(blank)* | `Ice Blue = manual input \| Zinc = ...` | `#F8FAFC`, `#52525B` ink, 19pt |
| **7** | *(blank separator)* | | | 10pt spacer |
| **8+** | **Section Header** | *(blank)* | *(blank)* | Cool Slate `#F1F5F9`, `#0F172A` Bold, 24pt |
| **9+** | Metric rows & Analysis sub-rows | Quarter-scoped target | Values / Formulas | Ice Blue / Zinc / Amber fills, `#E2E8F0` borders, conditional `"N/A"` -> Amber |
| **Bottom** | `Notes` | *(blank)* | Concise weekly note / doc pointer | Cool Slate header + hairline cells |

---

## Standard Formulas (Google Sheets + Excel Compatible)

- **WoW Change (`wow`)**:
  `=IF(ISBLANK(<c><r>),"",IFERROR(<c><r>/<next><r>-1,"N/A"))` *(Oldest col static Amber `"N/A"`; dynamic `"N/A"` colored Amber via conditional formatting)*
- **4-Week Avg (`rolling_4w`)**:
  `=IF(ISBLANK(<c><r>),"",AVERAGE(<c><r>:<c+3><r>))` *(Oldest 3 cols static Amber `"N/A"`)*
- **QTD Total / YTD Total (`qtd_sum`)**:
  `=IF(ISBLANK(<c><r>),"",SUM(<c><r>:$<oldest_col><r>))`
- **Carryover Cumulative Metric (`cumsum:<id>`)**:
  On `Q1` (first year): `=IF(ISBLANK(<c><sr>),"",SUM(<c><sr>:$<oldest><sr>))`. On `Q2`–`Q4` or subsequent years, adds prior quarter/year totals (`+SUM('<prev_tab>'!$C<sr>:$<prev_oldest><sr>)`) so cumulative totals never reset at quarter boundaries.
- **Target Delta (`vs_target`)**:
  `=IF(OR(ISBLANK(<c><r>),ISBLANK($B<r>)),"",IFERROR(<c><r>/$B<r>-1,"N/A"))`
- **QoQ Delta (`vs_prior_q`)**:
  Aligned by **Week-of-Quarter offset from the oldest (rightmost) column**, comparing Week `w` in the current quarter to Week `w` in `<prev_q>` even when quarters differ in week count.
- **YoY Delta (`yoy`)**:
  Compares Week `w` on `<Q_or_FY_tab>` against the matching week on the prior year's tab (`=IF(OR(ISBLANK(<c><r>),ISBLANK('<prev_yr_tab>'!<prev_c><r>)),"",IFERROR(<c><r>/'<prev_yr_tab>'!<prev_c><r>-1,"N/A"))`, or Amber `"N/A"` when no prior year exists).
