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

## Sheet procedure

1. Resolve the existing native spreadsheet ID. Read metadata for exact titles, sheet IDs, grid bounds and chart IDs. Do not use or replace a private reference report for testing.
2. Read bounded row-4 date headers, the identity column, labels, targets and the intended destination cells, including formulas, notes and validation. `--active-tab-first` changes tab order; it does not move the observed week to column C.
3. Compare `row_signature` and `catalog_signature`. A changed row layout requires explicit row/chart reconciliation. A changed catalog updates labels and quarter-scoped targets in A:B across all managed tabs. Neither case authorises replacing custom tabs.
4. For the reporting date, map the quarter and Full Year columns by their actual date headers. The plan's `expected_column` is a local reference; remap it if live columns differ. Verify referenced formulas still address the intended metric rows after any live structural edits.
5. Apply the planned bounded ranges through the available connector. The Google Drive plugin exposes `batch_update_spreadsheet`; other connectors may use different names. Preserve formulas by sending `formulaValue`, numbers as `numberValue`, text as `stringValue`, and blanks as empty cell objects with the `userEnteredValue` field mask. Never send a stringified request body.
6. Apply changed formatting only to the affected managed ranges. Preserve cell notes, validation and comments by omitting those fields from content writes. Preserve the hidden identity column. Copy no charts or custom tabs from the generated workbook over their live counterparts.
7. Read back exact dates, values, blanks versus zero, formulas, labels, targets, reviewed Notes links, custom-tab sentinels, chart IDs and comments. Inspect rendered layout. Mark Sheet sync verified only after these checks.

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

### Connectors that expose only value-range writes

Some connectors expose `modify_sheet_values` rather than raw `updateCells` requests. Check the actual tool schema before using this route:

- Use bounded, quoted tab ranges and explicit `value_input_option`. Separate `RAW` text writes from `USER_ENTERED` numbers and formulas. Keep labels and numeric-looking text literal; do not let a label beginning with `=` become a formula.
- Preserve numeric zero. Clear intended blank cells explicitly with the connector's clear operation; omission is not a clear. Never clear the whole destination before rewriting it.
- A values-only operation cannot apply table formatting or establish chart/comment preservation. Use separate supported operations and readback, or report those capabilities as pending.
- If live date columns differ from the plan, stop formula writes until their references are reconciled. Remapping a range alone does not repair formulas inside it.
- If the connector cannot preserve required types, blanks or existing content, stop that destination and report the missing capability. A different wrapper name does not establish equivalent behaviour.

## Doc procedure

1. Read the native document's revision ID, tab IDs, headings, table cells and links. Select the dated review by its exact date. Preserve earlier completed reviews and all unrelated tabs.
2. Reconcile numeric highlights in the dated Markdown review against the fresh `wpr-review-draft.md`. The selected dated review remains authoritative for the final Markdown, HTML and archive exports.
3. Update only the matching date section, paragraphs or table cells. If absent, insert that date once. Repeated runs must find and update the same section. Use native tables and link text, not flattened Markdown tables or raw link syntax.
4. Send `write_control.requiredRevisionId` with the current revision. Calculate indexes in UTF-16 units. Within a batch, insert text at descending positions or account for every earlier index shift. On revision conflict, re-read and reconcile; do not blindly retry.
5. Apply semantic paragraph headings first, then Inter typography to their text ranges so the destination's default named style does not reset the typeface. Apply Cool Slate table headers. Enumerate every native table in the updated date section; style each header row, including tables nested in later archive weeks when those weeks are explicitly in scope. Do not assume `table 1` is the only table.
6. Read back article/post titles, clickable target URLs, numeric cells, action status, both table headers and the prior review. Verify that the date heading occurs once.

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

The Skill supplies a collector example, local build/import commands, a sync planner and these operating instructions. It does not supply a scheduler or an unattended connector executor. A project's runner must implement checkpoints, bounded attempts and meaningful nonzero exit status for pending work. Development-only rehearsal tools are kept outside the installed Skill.

Live synthetic verification on 18 November 2026 covered repeat date-scoped writes, label/target changes, prior-week retention, a custom tab, a chart, cell notes, a Drive comment, two native Doc tables, hyperlink retention, all table headers and a four-week native Sheets XLSX export/import round trip. Test destinations contain invented data. These checks do not establish unattended scheduling reliability in another project.
