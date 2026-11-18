# Version 1.1.0 verification

Checked on 18 November 2026. All fixtures are invented; no private reference data is included in the repository.

| Area | Evidence |
| --- | --- |
| Regression suite | 66 standard-library tests pass with `python -B -m unittest discover -s tests`. |
| File preservation | Changed-cell and no-op CSV/XLSX imports, surrounding Markdown, source links, cell notes, uncatalogued rows, extra columns, BOM, CRLF and simulated flush/replace failures. |
| Period arithmetic | Adjacent dates, gaps, four complete consecutive periods, valid zero, zero denominator, preview/stale/unavailable states, definition changes, cross-year totals and spreadsheet-compatible display rounding. |
| Validation and round trip | Wrong weekdays and malformed numeric values rejected before writes; all four bundled fixture weeks import from fresh XLSX and native Sheets export, including a renamed metric label. |
| Reviewed exports | Final Markdown, HTML and archive use the same dated source; numeric draft remains separate; links render safely. |
| Actions | Only Decisions tables contribute carry-over; status retained; unrelated and future reviews excluded; reviewed summary links reach both reporting tabs. |
| Creator example | Explicit offsets, exclusive/inclusive boundaries, daylight-saving transition, preview/failed/stale captures, comparable counters, verified zero and read-only history preservation. |
| Custom formulas | Numeric arithmetic evaluates through a restricted AST; missing values, unsupported syntax, code-like expressions and division by zero remain unavailable. |
| Build checks | Both example configurations validate and produce six outputs. Workbook XML parses; date caches, hidden metric IDs and the merged frozen legend are present. Engine and example collector parse with Python 3.8 grammar; runtime tests ran on Python 3.14. |

## Live synthetic connector checks

The existing Google Drive connector was used against new reports containing invented data. No private reference destination was modified.

- Repeated writes updated the same interior date column on quarter and Full Year tabs.
- Display labels and quarter-scoped targets updated independently of row-layout signatures, including catalog updates to other managed quarters.
- Prior-week values, custom-tab sentinel, chart ID, cell notes and a Drive comment survived scoped writes.
- Google Sheets calculated the complete four-week average correctly and returned unavailable values for incomplete windows.
- A full native XLSX export imported all four fixture weeks into an empty local target using stable metric IDs.
- Revision-guarded Docs edits preserved the prior review, the single current-date heading, two native tables and a hyperlink. Both table headers were styled.
- Every populated Sheet tab, the custom chart and the Doc were inspected in the browser. The wrapped legend remains visible inside frozen columns; empty future periods are neutral.

These checks establish the tested connector path, not unattended scheduling reliability or compatibility with every agent's connector. Follow [connector-sync.md](connector-sync.md) for setup, readback and partial-failure handling.
