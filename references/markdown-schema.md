# Markdown Source-of-Truth Schema

All Weekly Product Review state lives in `wpr/` as plain, agent-readable Markdown. `scripts/wpr_sync.py` parses these exact structures deterministically.

## Directory Layout

- `wpr/wpr-config.md`: Metadata, style options, product system map, metric catalog, data source registry, and metric/target changelog.
- `wpr/metrics-data.md`: Weekly metric values (newest week at top).
- `wpr/collect_wpr.py`: Optional project-specific collector script for local/API/export sources.
- Collector outputs should follow [collector-contract.md](collector-contract.md); see the fully synthetic [creator example](../examples/creator-wpr/README.md).
- `wpr/reviews/YYYY-MM-DD-wpr.md`: Weekly review brief (highlights, carry-over actions, anecdotes, discussion, decisions).

---

## 1. `wpr/wpr-config.md`

```markdown
# WPR Config

## Metadata
- **Product / Program Name**: Acme App
- **Year**: 2026
- **Week Ending Day**: Friday
- **Meeting Cadence**: Mondays 09:00 UTC (60 mins)
- **Owners / Attendees**: PM, Engineering, Design, Growth, Support
- **Style**: standard
- **Google Sheet ID**: 
- **Google Doc ID**: 
- **Google Sheet URL**: 
- **Google Doc URL**: 

## Product Machine Map
- **Customer Journey**: Visit landing page -> Sign up -> Complete first workflow -> Weekly active -> Upgrade to paid -> Renew/Refer
- **Value Delivery**: Reliable fast execution, <2h support response, weekly releases
- **Money & Risk**: MRR, paid acquisition spend, infra cost, churn, P1 incidents
- **OKR Boundary**: Q4 OKRs focus on Enterprise SSO launch; Weekly Product Review tracks core growth, reliability, and support health.

## Metric Catalog

| Section | ID | Metric | Type | Format | Target | Analyses | Formula | Owner | Source / ETA |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| User Growth | new_users | New Users | manual | int | Q1: 20; Q2: 30; 35 | qtd_sum | | Growth | Mixpanel signup export |
| User Growth | total_users | Total Users | calculated | int | | | cumsum:new_users | Auto | Calculated from New Users |
| User Growth | dau | Daily Active Users | manual | int | 100 | wow, yoy | | Product | Amplitude DAU (Fri) |
| Customer Journey | landing_visits | Landing Page Visits | manual | int | 2500 | rolling_4w, vs_prior_q | | Marketing | GA4 weekly sessions |
| Customer Journey | engagement_mins | Engagement (mins/user) | manual | float | 20.0 | vs_target | | Product | PostHog avg session |
| Revenue | weekly_mrr | New MRR ($) | manual | currency | 2000 | qtd_sum, wow | | Finance | Stripe weekly report |
| Money & Risk | nps | Customer NPS | not-collected | float | 45 | | | Support | ETA: 2026-12-15 |

## Data Sources

| Metric IDs | Source System | Location / URL / Query | Date-Range Filter | Method | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| new_users, dau | Mixpanel / Amplitude | Project dashboard -> Weekly Fri | Past 7 days | api/mcp | Export or API query |
| weekly_mrr | Stripe | Billing -> Weekly Net New MRR | Past 7 days | csv-export | Or Stripe API |
| landing_visits | GA4 | Reports -> Acquisition | Past 7 days (UTC) | local-script | Pulled via wpr/collect_wpr.py |

## Metric & Target Changelog

| Effective Date | Metric ID | Change Type | Old -> New | Reason |
| :--- | :--- | :--- | :--- | :--- |
| 2026-04-03 | new_users | Target Updated | 20 -> 30 | Q2 growth step-up |
```

### Field Reference for `wpr-config.md`

- **Metadata fields**:
  - **Product / Program Name** *(also accepts `Product Name`, `Program Name`, `Business Name`)*: Display title for briefs and exports.
  - **Year**: Starting calendar year (e.g., `2026`); multi-year history in `metrics-data.md` automatically adds tabs for every year present.
  - **Week Ending Day**: `Monday` through `Sunday` (default `Friday`).
  - **Meeting Cadence** / **Owners / Attendees**: Printed in the header of weekly review briefs.
  - **Style** (optional): `standard` (default) or `no-em-dash` (replaces `—` with `-` in generated briefs and placeholder cells to respect workspace style rules).
  - **Google Sheet ID / URL** & **Google Doc ID / URL**: Stored links for in-place syncs (`Review Sheet` / `Review Doc` links in briefs).
- **Metric Catalog fields**:
  - **Section**: Spreadsheet area header (`User Growth`, `Reach & Authority`, `Delivery`, `Money & Risk`, etc.).
  - **ID**: Lowercase `snake_case` unique identifier (keep stable across history).
  - **Metric**: Display name in Column A.
  - **Type**: `manual` (Ice Blue `#EFF6FF`), `calculated` / `automated` (Zinc `#FAFAFA`), or `not-collected` (Amber `#FFEDD5`).
  - **Format**: `int`, `float`, `currency` (`$#,##0`), or `percent` (`0.0%`).
  - **Target**:
    - Global target: single value (e.g., `30`, `0.40`) applied to all quarters.
    - **Quarter-scoped targets**: semicolon-separated `Q<n>: <val>` or `Q<n> <YY>: <val>` entries with an optional fallback default (e.g., `Q1: 20; Q2: 30; Q3 26: 40; 45`) so mid-year target changes do not overwrite earlier quarters' `Target`.
  - **Analyses** (comma-separated):
    - `wow` -> `WoW Change`
    - `rolling_4w` -> `4-Week Avg`
    - `qtd_sum` -> `QTD Total` (and `YTD Total` on Full Year)
    - `vs_target` -> `Target Delta`
    - `vs_prior_q` -> `QoQ Delta` (aligned by Week-of-Quarter offset)
    - `yoy` -> `YoY Delta` (compares against the same week on the prior year's tab)
  - **Formula** (for `calculated` metrics):
    - `cumsum:<metric_id>` -> cumulative sum carrying across quarters and years.
    - `ratio:<num_id>/<den_id>` -> ratio of two metrics.
    - `diff:<a_id>-<b_id>` -> difference of two metrics.
    - Raw spreadsheet formula using `{col}`: numeric constants, metric-row references, parentheses and `+`, `-`, `*`, `/` also evaluate in Python briefs (e.g., `={col}9/{col}15`). Other spreadsheet functions remain workbook-only and show unavailable values in generated briefs; arbitrary code is never executed.
- **Data Sources & Changelog tables**:
  - `## Data Sources`: `Metric IDs`, `Source System`, `Location / URL / Query`, `Date-Range Filter`, `Method` (`local-script`, `api/mcp`, `browser`, `csv-export`, `manual`), `Notes`.
  - `## Metric & Target Changelog`: `Effective Date`, `Metric ID`, `Change Type`, `Old -> New`, `Reason`.

---

## 2. `wpr/metrics-data.md`

Weekly metric entries stored **newest week at the top**. `scripts/wpr_sync.py` supports multiple calendar years in the same file.

Optional metadata directly below a week heading:

```markdown
- Period State: preview
- Comparison Group: weekly-cutoff-v1
```

- New weeks start as `preview`. After checking the reporting cutoff, complete source coverage and values, set `Period State: closed` explicitly. Numeric preview values are excluded from exported calculations.
- Legacy weeks without `Period State` remain closed for compatibility. Mark any genuinely provisional rows explicitly.
- `Comparison Group` identifies comparable definitions/windows. A change breaks automatic comparisons across that boundary. WoW uses exactly seven days earlier; rolling averages require four consecutive closed periods and four numeric values. Zero counts as numeric; a zero denominator has no percentage change.
- Additional cell statuses are `preview`, `stale`, `unavailable` and `verified-zero`; the last requires numeric zero. Use blanks for unavailable values rather than text in numeric fields.

You can keep preview observations, source notes and links around the weekly tables. `add-week`, `import-csv` and `import-xlsx` preserve that content, existing cell notes, uncatalogued rows and extra table columns. Imports patch changed cells; a no-op leaves the file byte-for-byte unchanged, including its UTF-8 BOM and line endings. Changed files use a flushed temporary file in the same directory and atomic replacement. Duplicate weeks or duplicate metric rows are rejected before writing to avoid ambiguous updates.

Pass `--dry-run` to any of these three commands to print a proposed diff without writing. Preview output can contain your metric values and private notes; review it locally.

```markdown
# Weekly Metrics Data

## Week 2026-11-13
- Quarter: Q4 26 | Week of Quarter: 7 | Week of Year: 46

| ID | Metric | Value | Status | Note |
| :--- | :--- | :--- | :--- | :--- |
| new_users | New Users | 42 | manual | Product Hunt mention drove spike |
| total_users | Total Users | | calculated | |
| dau | Daily Active Users | 118 | manual | [Restated 2026-11-20: excluded bot traffic] |
| nps | Customer NPS | | not-collected | ETA: 2026-12-15 |
```

- **Restatements:** When revising a historical week's value, prefix the `Note` with `[Restated YYYY-MM-DD: <reason>]`. `wpr_sync.py` surfaces restatements in the review brief.

---

## 3. `wpr/reviews/YYYY-MM-DD-wpr.md`

Source of truth for the companion Google Doc (and weekly `Notes` summary). When `reviews/YYYY-MM-DD-wpr.md` already exists, `build` renders it into `wpr-review-brief.html` and `wpr-review-archive.md` (pass `--overwrite-review` to regenerate the draft from scratch). Sections:
1. `## 1. Metric Highlights & Anomalies` (`| Section | Metric | This Week | Prior Week | WoW % | 4-Wk Avg | Target | Signal |`, showing `Pending input` for blank manual metrics)
2. `## 2. Carry-Over Actions Review`
3. `## 3. Customer, Sales & Support Anecdotes`
4. `## 4. Discussion & Root-Cause Notes`
5. `## 5. Decisions & Actions` (`### Improve the Spreadsheet` and `### Change the Product or Workflow`)

---

## 4. `scripts/wpr_sync.py` CLI Commands

- `validate --wpr-dir wpr`: Check catalog IDs, types, formats, formulas, analyses, and missing manual entries.
- `add-week --wpr-dir wpr [--date YYYY-MM-DD] [--force] [--dry-run]`: Insert a blank preview week in date order without regenerating existing weeks. Reject dates on the wrong weekday. `--force` resets the specified week's metric cells and reopens it as preview while retaining its comparison group and surrounding content.
- `import-xlsx --wpr-dir wpr --xlsx path.xlsx [--dry-run]`: Pull manual metric edits from all quarter tabs of an `.xlsx` export into `metrics-data.md`.
- `import-csv --wpr-dir wpr --csv path.csv [--dry-run]`: Pull manual metric edits from a single-tab `.csv` export.
- `build --wpr-dir wpr --out-dir wpr-output [--active-tab-first] [--overwrite-review]`: Generate `wpr-workbook.xlsx`, `wpr-review-brief.md`, `wpr-review-brief.html`, `wpr-review-archive.md`, `sheets-payload.json`, and starter `reviews/<date>-wpr.md` (if absent).
- `plan-sync --payload wpr-output/sheets-payload.json [--previous previous-payload.json] --date YYYY-MM-DD --out sync-plan.json`: Generate bounded date-keyed writes and separate catalog updates without network access. Inspect live dates and row layout before applying.

`build` also writes `wpr-review-draft.md` with fresh generated highlights. The selected dated review supplies all final brief exports; reconcile its numeric tables against the draft before syncing. Add `- **Reviewed Summary:** <reviewed note and optional link>` to that dated review for Sheet Notes. If omitted, Notes use up to two actions from its Decisions tables, never arbitrary metric annotations.

Generated workbooks persist numeric date caches beside formulas and include a hidden `Metric ID` column. XLSX imports use those stable identities, accept valid zero, validate all candidate values before saving, and report unmatched rows and uncomputed headers with counts and reasons. Display-label changes do not change metric identity.
