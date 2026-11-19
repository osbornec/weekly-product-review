# Synthetic creator review

All names, URLs, figures and events in this example are invented. It demonstrates a publication programme with account-wide measurements, separate content items, a cumulative article counter and dated activity events.

## Preview in the normal scorecard

1. Use the existing scorecard. Put provisional figures in the date column as display text, with an amber fill and a **Preview** date label. Use `0 so far` for a partial zero and leave comparisons and cumulative totals blank.
2. Put the current coverage window and the existing Doc link together in the coverage cell. Leave the closed-week highlights row for closed results. Add a separate view only when requested or useful for independent data, such as item-level evidence with a different scope.
3. After cutoff, keep the same date, remove the preview format and publish verified numbers, including verified zero. Clear unverified figures and name each missing source. Ordinary blank inputs are neutral, populated manual results are ice blue, and explicit pending or N/A cells are amber.

Keep the source window and capture time beside the figure. Put an expected gap, such as a missing comparable article baseline, in the metric's `Gap Reason`. The validator groups metrics with the same reason. Keep audience splits, raw item counters, separate dashboard windows and their receipts in the evidence log linked from Markdown. Bring a diagnostic into the scorecard when it affects a weekly decision.

## Run the examples

Copy this example to `creator-example/` in your project. Run from the project folder and set `$skillRoot` to the installed Skill folder or the development checkout's `skills/weekly-product-review/` folder.

```powershell
$skillRoot = 'C:/path/to/weekly-product-review'
python creator-example/collect_wpr.py --as-of 2027-02-12T17:15:00+01:00
python creator-example/collect_wpr.py --input creator-example/capture.partial-close.example.json --as-of 2027-02-05T17:10:00+01:00
python "$skillRoot/scripts/wpr_sync.py" validate --wpr-dir creator-example
python "$skillRoot/scripts/wpr_sync.py" build --wpr-dir creator-example --out-dir wpr-output
```

- The collector reads `capture.example.json` and prints candidate values. It never edits `metrics-data.md`, calls a service or publishes anything.
- The main fixture contains a complete capture. Its Markdown week starts as a preview. The partial-close fixture reproduces the older closed week with verified reach and zero outcomes, a stale visitor feed, and an article counter without a baseline. Use the `Capture / Coverage` and `Gap Reason` columns to carry the evidence into the review.
- `capture.example.json` gives account-wide reach, two typed posts and a linked article with its own counter. The article's lifetime total is not a weekly measure; the comparable difference is 27.
- Preview, stale and inaccessible captures return blank candidate values while retaining observed counts for diagnosis. Verified zero is a separate state. Existing closed history remains unchanged because collection is read-only.
- Preserve window and scope when dashboard labels look alike. The partial-close fixture keeps both reads of a rolling impressions total beside a separate since-publication count. It also records account and post-attributed profile viewers separately. These records stay outside the weekly candidate values.
- `metrics-data.md` keeps a pre-publication baseline outside the weekly series. It must not be used to fill missing weekly periods.
- Follow the [collector contract](../../references/collector-contract.md) for cutoff changes, timezone offsets, failed captures and retries.

## Reconcile daily workbooks

The [synthetic workbook adapter](workbook_exports.py) checks files in a configured download folder. Its example schema has an `Export info` tab for the account, selected UTC dates and range totals, and a `Daily` tab with one row per UTC day. Other tabs can hold demographics or item diagnostics.

```powershell
python "$skillRoot/examples/creator-wpr/workbook_exports.py" `
  --downloads "C:/path/to/synthetic-downloads" --filename "Creator export.xlsx" `
  --account reed-lab --first-day 2028-03-05 --last-day 2028-03-18 `
  --requested-at 2028-03-19T14:00:00-04:00 --as-of 2028-03-19T14:05:00-04:00
```

Use the observed timestamps and expected bounds for the specific attempt. Adapt the workbook reader to the provider's actual tab and column schema.

1. Request the last 14 complete UTC days. Check a newly landed file against the requested account and dates, even if the browser event timed out. Record its timestamp and checksum.
2. Stage accepted daily rows and hold conflicting values for corroboration. Replay the same workbook to check that it adds zero rows.
3. Roll seven complete UTC dates into the review. Keep export engagements, dashboard social engagements, native profile windows and local event cutoffs separate. Record the date span actually used.
