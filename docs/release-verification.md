# Version 1.1.0 verification

The development build passed 100 standard-library tests on Windows with CPython 3.8.10 and 3.14.5. All fixtures are synthetic. The tagged `v1.1.0-rc.1` used the earlier 91-test suite and a 19-file Skill package. See [recovery and compatibility](recovery-and-compatibility.md) and the [independent beta](blind-beta-verification.md) for those earlier results.

| Area | Evidence |
| --- | --- |
| Regression suite | Run `python -B -m unittest discover -s tests` from a checkout. |
| File preservation | Changed-cell and no-op CSV/XLSX imports, surrounding Markdown, source links, cell notes, uncatalogued rows, extra columns, BOM, CRLF and simulated flush/replace failures. |
| Period arithmetic | Adjacent dates, gaps, four complete consecutive periods, valid zero, zero denominator, preview/stale/unavailable states, definition changes, cross-year totals and spreadsheet-compatible display rounding. |
| Validation and round trip | Wrong weekdays and malformed numeric values rejected before writes; all four bundled fixture weeks import from fresh XLSX and native Sheets export, including a renamed metric label. |
| Reviewed exports | Final Markdown, HTML and archive use the same dated source; numeric draft remains separate; links render safely. |
| Actions | Only Decisions tables contribute carry-over; status retained; unrelated and future reviews excluded; reviewed summary links reach both reporting tabs. |
| Creator example | Explicit offsets, exclusive/inclusive boundaries, daylight-saving transition, preview/failed/stale captures, comparable counters, verified zero and read-only history preservation. |
| Workbook verification | A fresh, complete XLSX for the expected account and dates passes even if the browser event timed out. Tests cover duplicate-name suffixes, stale files, incomplete workbooks, wrong ranges and ledger readback. |
| Daily reconciliation | The creator example checks 14 overlapping UTC days and rolls up seven complete days. An exact replay adds zero rows. Conflicting observations need corroboration before restatement. Open days and unresolved gaps stay outside the affected weekly totals. |
| Source evidence | UTC creator totals, native profile windows and local event cutoffs stay separate. Tests cover item aliases, repeat snapshots, linked article and post identities, a cutoff-minute event, a booking held in a later week and partial close with verified zero. |
| Reporting readback | Local fixtures check preview colours and numeric types, heading order and anchors, and table and link preservation. A simulated chart-position rejection exercises a smaller table write and checks that the existing chart survives. |
| Coverage and gaps | Validation groups expected gaps by reason. The generated brief shows source coverage beside the result, including a known baseline gap during a preview. |
| Custom formulas | Numeric arithmetic evaluates through a restricted AST; missing values, unsupported syntax, code-like expressions and division by zero remain unavailable. |
| Build checks | Both examples validate and build six output files. Workbook XML contains date caches, hidden metric IDs and the merged legend across frozen columns. |

## Earlier live synthetic connector checks

Earlier verification used the Codex Google Drive plugin with separate synthetic reports. The latest workbook and reporting follow-up uses the local tests above.

- Repeated writes updated the same interior date column on quarter and Full Year tabs.
- Display labels and quarter-scoped targets updated independently of row-layout signatures, including catalog updates to other managed quarters.
- Prior-week values, custom-tab sentinel, chart ID, cell notes and a Drive comment survived scoped writes.
- Google Sheets calculated the complete four-week average correctly and returned unavailable values for incomplete windows.
- A full native XLSX export imported all four fixture weeks into an empty local target using stable metric IDs.
- Revision-guarded Docs edits preserved the prior review, the current date heading, two native tables and a hyperlink. Both table headers were styled.
- Every populated Sheet tab, the custom chart and the Doc were inspected in the browser. The wrapped legend remains visible inside frozen columns; empty future periods are neutral.
- In a separate rollover and close test, the Doc inserted the new week above the older week. Closing the new week and rerunning the older one preserved one Heading 1 per date, both heading anchors, descending order and links in untouched sections.
- On the quarter and full-year Sheet tabs, preview values appeared as text with calculations blank. At close, verified numbers included a verified zero. The coverage cell named the missing source and carried the Doc link.
- The format regression retest started with General result formats. The close plan restored `20.0%` week over week and `18.0` for the four-week average on both tabs. All 16 planned number formats matched; the prior week and Doc link were preserved.

Follow the [connector procedure](../skills/weekly-product-review/references/connector-sync.md) for setup, live readback and partial failures.

## Installed Skill packaging

The installable boundary is `skills/weekly-product-review/`. Development tests, this verification record, repository documentation, promotional images and the B2B demonstration remain outside it. The runtime has its own MIT licence and a compact creator example.

Run `python -B tests/verify_skill_install.py --skills-cli /path/to/skills/bin/cli.mjs --report .local/install-verification.json` from a clean checkout. The check uses an existing CLI, disables telemetry and installs from a temporary copy of Git-visible files. Synthetic markers exercise the package boundary.

- Skills CLI 1.9.0 discovered and installed one Skill with the unchanged name `weekly-product-review`.
- The development package contains 20 runtime files, including the creator workbook adapter. Byte hashes match the source. The package excludes tests, promotional images, development reports and local markers.
- All 32 package link and entrypoint resource checks passed. Nine installed workflow groups passed on each Python version. Synthetic XLSX regression tests cover the workbook adapter's behaviour.
- From a separate project directory, the installed collector returns eight expected synthetic candidates; creator validation/build, template scaffolding, CSV import, manual validation/build, XLSX round trip, date-keyed sync planning, add-week dry run and add-week pass.
- Each build produces the six expected outputs. Dry runs preserve source bytes, and the installed files remain unchanged after the workflows.
