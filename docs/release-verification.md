# Version 1.1.0 verification

Checked on 18 November 2026. All fixtures are invented; no private reference data is included in the repository. The original release checks below used 66 tests; the subsequent [recovery and compatibility verification](recovery-and-compatibility.md) expands the suite to 77 tests and adds actual Python 3.8 execution and a one-shot local scheduler check.

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

These checks establish the tested connector path, not unattended scheduling reliability or compatibility with every agent's connector. Follow [connector-sync.md](../skills/weekly-product-review/references/connector-sync.md) for setup, readback and partial-failure handling.

## F08: installed Skill packaging

The installable boundary is `skills/weekly-product-review/`. Development tests, this verification record, repository documentation, promotional images and the B2B demonstration remain outside it. The runtime has its own MIT licence and a compact creator example.

Run `python tests/verify_skill_install.py --skills-cli /path/to/skills/bin/cli.mjs --report .local/f08-install-verification.json` from the development repository. The check uses an existing CLI, disables telemetry, copies Git-visible files into a temporary source and installs into a temporary project. Synthetic exclusion markers exercise the boundary without reading private files.

- Skills CLI 1.9.0 discovered and installed one Skill with the unchanged name `weekly-product-review`.
- The installed manifest contains exactly 18 runtime files. Byte hashes match the source; no tests, promotional images, development reports or local markers are installed.
- All relative package links and the entrypoint's resource paths resolve inside the installed Skill.
- From a separate project directory, the installed collector returns eight expected synthetic candidates; creator validation/build, template scaffolding, CSV import, manual validation/build, XLSX round trip, date-keyed sync planning, add-week dry run and add-week pass.
- Each build produces the six expected outputs. Dry runs preserve source bytes, and the installed files remain unchanged after the workflows.
- The full development regression suite remains outside the installed folder and passes all 66 tests.

The public installation command remains `npx skills add osbornec/weekly-product-review`. This check verifies local discovery and installation of the new structure; the remote command continues to use the existing published version until a release is explicitly authorised. No global Skill installation is changed.
