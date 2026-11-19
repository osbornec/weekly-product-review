# Windows and connector-first sync

Use a connector when the destination has custom tabs, charts, comments or reviewed document content. Whole-workbook replacement is not a preservation strategy. All examples below use invented data and placeholder identifiers.

## Resolve the installed script

Run the script from the installed skill folder, even when the project working directory is elsewhere. Use the actual skill path supplied by your agent, rather than assuming `scripts/` exists in the project.

```powershell
$skillRoot = 'C:\path\to\installed\weekly-product-review'
$wprScript = Join-Path $skillRoot 'scripts\wpr_sync.py'
if (-not (Test-Path -LiteralPath $wprScript)) { throw 'Resolve the installed skill folder first' }
python $wprScript validate --wpr-dir wpr
python $wprScript build --wpr-dir wpr --out-dir wpr-output --active-tab-first
python $wprScript plan-sync --payload wpr-output/sheets-payload.json --previous wpr-output/previous-payload.json --date 2027-02-12 --out wpr-output/sync-plan.json
```

Omit `--previous` for the first sync. Save the successfully verified Sheet payload as `previous-payload.json` only after Sheet readback, not merely after submitting a write. This checkpoint belongs to the Sheet; a failed Doc update must not discard it. The plan command writes a local JSON plan and makes no network calls.

## Google Drive plugin preflight

Run this check in the agent session before any authorized Google sync. The Python commands build local outputs independently of the plugin. If the run is local-only, skip this check and build from local inputs.

1. Check that the Google Drive plugin is available in the current session. For each requested destination, confirm it offers the required native read and update tools. Use the project's configured Sheet and Doc IDs or URLs. A missing target is unconfigured. First-time creation requires an explicit setup request and the appropriate create tool.
2. Make a read-only call through the plugin to each exact target. Read Sheet metadata and the relevant date headers or read the Doc structure and revision. For edit access in Codex, request `capabilities(canEdit)` through the plugin's `get_file_metadata` tool. Interpret the evidence per destination using the table below.
3. If the plugin is missing, disconnected, missing a required tool, or returns an access error, leave the affected destination pending and report the specific blocker. Complete validation and the local build using available inputs. Continue an authorized sync for any other destination that passed. Keep configured IDs intact. A substitute connector or replacement file requires a separate user choice.

| Edit evidence on the exact target | Decision |
| --- | --- |
| `canEdit: true` | Proceed with the authorized scoped write and verify by readback. |
| `canEdit: false` or an explicit permission denial | Keep this destination blocked. Ownership, sharing flags and successful reads do not override a denial. |
| `canEdit` omitted | Try a broader metadata or permissions read. Accept a confirmed owner or editor role for the authenticated identity on that file. An owner listed without a match to the connected identity, sharing capability alone, and a successful content read are insufficient. |
| Evidence still unavailable or contradictory | Report edit access as unconfirmed and keep this destination pending. |

Record the evidence used for each destination separately. In a synthetic example, a Sheet response omits `canEdit` but the broader read confirms the connected account owns the Sheet. That Sheet can proceed. If the Doc reports `canEdit: false`, keep the Doc blocked and continue the local build. Any denial returned by the actual write supersedes preflight evidence.

Report the local output folder and separate results for the Sheet and Doc. For example, “Local build complete. Sheet sync blocked because edit access was denied. Doc updated and verified.” If a live Sheet export was unavailable, also report that any unimported manual edits are absent from the local build.

## Sheet procedure

1. Resolve the existing native spreadsheet ID. Read metadata for exact titles, sheet IDs, grid bounds and chart IDs. Do not use or replace a private reference report for testing.
2. Read bounded date headers, the identity column, labels, targets and destination cells, including formulas, notes, validation and link targets. The plan's `sheet_role` and `row_layout` describe the generated workbook. Resolve the actual tabs, date columns and rows before applying it.
3. Compare `row_signature` and `catalog_signature`. A changed row layout requires explicit row/chart reconciliation. A changed catalog updates labels and quarter-scoped targets in A:B across all managed tabs. Neither case authorises replacing custom tabs.
4. For the reporting date, map each managed tab by its role and date key. Match rows by metric ID or by coverage/highlights purpose. Reconcile live offsets and formula references when rows or columns have moved. Use project-defined names and sheet IDs for supplemental destinations.
5. Apply the planned bounded ranges through the available connector. The Google Drive plugin exposes `batch_update_spreadsheet`; other connectors may use different names. Preserve formulas by sending `formulaValue`, numbers as `numberValue`, text as `stringValue`, and blanks as empty cell objects with the `userEnteredValue` field mask. Never send a stringified request body.
6. Apply changed formatting only to the affected managed ranges. For each remapped cell in `number_formats`, set `userEnteredFormat.numberFormat` to its supplied Sheets type and pattern. Use a field mask limited to the number format for these requests. If a plan omits a cell's number format, keep its live format. Preserve cell notes, validation and comments by omitting those fields from content writes. Preserve the hidden identity column. Copy no charts or custom tabs from the generated workbook over their live counterparts.
7. Read back exact dates, values, blanks versus zero, formulas, labels, targets, reviewed Notes links, custom-tab sentinels, chart IDs and comments. Verify applied number formats and displayed results, including percentages and rolling averages at close. Inspect rendered layout. Mark Sheet sync verified only after these checks.

For a preview, keep the date key and date formula. Apply `date_header.number_format` with type `DATE`. Write `text_cells` as literal strings and keep comparison and cumulative cells blank. Use `coverage_cell` for the window and existing Doc link. At close, restore the date-only header. Apply the planned `number_formats` to metric and analysis cells. Send entries in `number_cells` as numbers, including verified zero. Clear unverified figures, name missing sources in the coverage cell and put closed highlights in `notes_cell`.

Example: a two-cell update in an already-resolved date column; indexes are zero-based.

```json
{
  "spreadsheet_id": "<resolved-native-id>",
  "requests": [{
    "updateCells": {
      "start": {"sheetId": 123, "rowIndex": 8, "columnIndex": 7},
      "rows": [
        {"values": [{"userEnteredValue": {"numberValue": 12}}]},
        {"values": [{"userEnteredValue": {"formulaValue": "=SUM(H9:J9)"}}]}
      ],
      "fields": "userEnteredValue"
    }
  }]
}
```

Create a native destination from the local XLSX only for an initial setup. Use the connector's native spreadsheet import action. For the return trip, export the complete native workbook as XLSX and run `import-xlsx --dry-run` before applying it; CSV covers one tab only.

### Backfill and supplemental readback

Before writing, list each intended destination and its expected date window, metric IDs and cell or record counts. Generate the date-keyed plan for every affected reporting date. Use bounded, separately authorized scopes for supplemental tables and charts.

| Synthetic destination | Verify after writing |
| --- | --- |
| Quarter and year scorecards | Match each date and metric ID against the authoritative record, including numeric values, unavailable blanks and the count of explicitly verified zeros. Check note capture timestamps, closed highlights and coverage link targets. Preserve the current preview and its formula. |
| Trend table and its chart | Compare each source's native date window, values and missing points. Read back the chart IDs and the intended source ranges. A correct table does not establish chart preservation. |
| Item breakdown | Match the expected dated rows by item ID, window and metric. Check the item hyperlinks along with the values. |

Verify text, native hyperlinks and notes independently of numeric values. After a value-only change, read back the hyperlink destination. If it is missing or wrong, restore it using a supported linked-text update and read it again. Update stale notes with a field mask limited to `note`; a correction must preserve the cell's value and formula.

Keep optional chart mutations separate from required data writes where possible. If a batch containing an optional chart positioning request is rejected, read back the table and chart metadata first. Retry once with the smaller supported write for the remaining table change. Verify the changed range and the existing chart again. Report unsupported optional changes and any unverified surface separately.

### Connectors that expose only value-range writes

Some connectors expose `modify_sheet_values` rather than raw `updateCells` requests. Check the actual tool schema before using this route:

- Use bounded, quoted tab ranges and explicit `value_input_option`. Separate `RAW` text writes from `USER_ENTERED` numbers and formulas. Keep labels and numeric-looking text literal; do not let a label beginning with `=` become a formula.
- Preserve numeric zero. Clear intended blank cells explicitly with the connector's clear operation; omission is not a clear. Never clear the whole destination before rewriting it.
- A values-only operation cannot apply table formatting or establish chart/comment preservation. Use separate supported operations and readback, or report those capabilities as pending.
- If live date columns differ from the plan, stop formula writes until their references are reconciled. Remapping a range alone does not repair formulas inside it.
- If the connector cannot preserve required types, blanks or existing content, stop that destination and report the missing capability. A different wrapper name does not establish equivalent behaviour.

## Doc procedure

1. Use one existing Google Doc for review history. In the flat `wpr/reviews/` folder, keep one `YYYY-MM-DD-wpr.md` file per reporting week. Derive the date from the project's configured week ending and validated dated record. Use `Week ending D Month YYYY` as both the Markdown H1 and the native Doc Heading 1. Put period status and source coverage below it. If editing a legacy review, update its heading only for the selected week and preserve the rest of its content.
2. Reconcile numeric highlights in the dated Markdown review against the fresh `wpr-review-draft.md`. The dated review remains authoritative for final exports. Keep preview observations labelled on the scorecard. At close, publish verified values and name missing sources.
3. Read the exact Doc before every write or retry. Include the current revision, selected tab, top-level headings, tables and links. Match the exact dated Heading 1 and update only through the next dated Heading 1 or the end of the Doc. If it is absent, insert it in descending week-ending date order. When a legacy heading could belong to the same week or obscure the section boundary, reconcile it before writing so you do not insert a duplicate or replace another week.
4. Use `plan-doc-sync --wpr-dir wpr --document doc-snapshot.json --date 2027-02-12 --out doc-plan.json` with the project's date. Give it the native snapshot's `revisionId` and `body.content`. For a tabbed Doc, put the selected tab's body in `body` and use its tab ID in request locations and ranges. When the heading exists, start edits at `body_start_index` to preserve the Heading 1 paragraph and its anchor. Apply only changes within that section, through the exclusive `end_index`. Send `writeControl.requiredRevisionId` in the native write. Preserve the terminal newline and insert a paragraph break when appending after text. Preserve native table structure and links. Docs indices are UTF-16 offsets. On conflict or retry, read the Doc again and recompute the bounds.
5. Apply semantic paragraph headings first, then Inter typography to their text ranges so the destination's default named style does not reset the typeface. Apply Cool Slate table headers. Enumerate every native table in the updated date section; style each header row, including tables nested in later archive weeks when those weeks are explicitly in scope. Do not assume `table 1` is the only table.
6. Read back the Doc. Verify exactly one matching dated Heading 1, descending week order, synced figures, status, coverage, links and table headers. Verify that untouched sections and their links match the prewrite read.

For each table's resolved start index, the Docs request shape is:

```json
{
  "updateTableCellStyle": {
    "tableRange": {
      "tableCellLocation": {
        "tableStartLocation": {"index": 142, "tabId": "<resolved-tab-id>"},
        "rowIndex": 0,
        "columnIndex": 0
      },
      "rowSpan": 1,
      "columnSpan": 2
    },
    "tableCellStyle": {"backgroundColor": {"color": {"rgbColor": {"red": 0.9451, "green": 0.9608, "blue": 0.9765}}}},
    "fields": "backgroundColor"
  }
}
```

Resolve the index, tab ID and column span from the actual table. Do not copy the illustrative index into a live document.

## Partial completion

Record independent states for collection, source reconciliation, build, Sheet sync and Doc sync. If either destination fails, retain the verified state of the other, record the failure and retry only the pending destination for the same reporting date. Do not claim a complete refresh while a destination is pending.

Keep a project-local checkpoint outside the installed Skill. For each destination, record its native ID, reporting date, intended content revision/hash, state (`pending`, `submitted`, `verified`) and last successful readback. Persist `submitted` before sending a write and mark `verified` only after readback. Keep source and destination credentials out of the checkpoint.

- A timeout or process exit can happen after a server has committed a write. Re-read the same date section/ranges before retrying. If the intended content is already present, verify it without submitting another write.
- Skip a previously verified destination only while its ID, reporting date and intended content revision still match; check for destination drift. An edited reviewed brief or changed metric/catalog requires a fresh comparison.
- Save the Sheet payload checkpoint independently of the Doc receipt. Keep pending/error state explicit when readback fails; a successful submission is not a successful refresh.
- On a Doc revision conflict, retain pending status, re-read and reconcile on the next bounded attempt. Do not reuse the stale revision or append a duplicate date section.

The Skill supplies local build and planning commands. If a project runs refreshes on a schedule, its runner must record checkpoints, bound its retries and return a nonzero exit status for pending work.
