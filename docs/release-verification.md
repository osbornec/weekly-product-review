# Version 1.1.0 verification

All fixtures are synthetic. The v1.1.0 candidate passed 91 standard-library tests on Windows with CPython 3.8.10 and 3.14.5. See [recovery and compatibility](recovery-and-compatibility.md) and the [independent beta](blind-beta-verification.md) for earlier test results.

| Area | Evidence |
| --- | --- |
| Regression suite | Run `python -B -m unittest discover -s tests` from a checkout. |
| File preservation | Changed-cell and no-op CSV/XLSX imports, surrounding Markdown, source links, cell notes, uncatalogued rows, extra columns, BOM, CRLF and simulated flush/replace failures. |
| Period arithmetic | Adjacent dates, gaps, four complete consecutive periods, valid zero, zero denominator, preview/stale/unavailable states, definition changes, cross-year totals and spreadsheet-compatible display rounding. |
| Validation and round trip | Wrong weekdays and malformed numeric values rejected before writes; all four bundled fixture weeks import from fresh XLSX and native Sheets export, including a renamed metric label. |
| Reviewed exports | Final Markdown, HTML and archive use the same dated source; numeric draft remains separate; links render safely. |
| Actions | Only Decisions tables contribute carry-over; status retained; unrelated and future reviews excluded; reviewed summary links reach both reporting tabs. |
| Creator example | Explicit offsets, exclusive/inclusive boundaries, daylight-saving transition, preview/failed/stale captures, comparable counters, verified zero and read-only history preservation. |
| Custom formulas | Numeric arithmetic evaluates through a restricted AST; missing values, unsupported syntax, code-like expressions and division by zero remain unavailable. |
| Build checks | Both examples validate and build six output files. Workbook XML contains date caches, hidden metric IDs and the merged legend across frozen columns. |

## Live synthetic connector checks

The Codex Google Drive plugin was used against separate reports containing invented data.

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
- The installed manifest contains 19 runtime files. Byte hashes match the source. The package excludes tests, promotional images, development reports and local markers.
- All 29 package links and entrypoint resource checks passed inside the installed Skill.
- From a separate project directory, the installed collector returns eight expected synthetic candidates; creator validation/build, template scaffolding, CSV import, manual validation/build, XLSX round trip, date-keyed sync planning, add-week dry run and add-week pass.
- Each build produces the six expected outputs. Dry runs preserve source bytes, and the installed files remain unchanged after the workflows.
