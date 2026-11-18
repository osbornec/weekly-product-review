# Synthetic creator review

All names, URLs, figures and events in this example are invented. It demonstrates a publication programme with account-wide measurements, separate content items, a cumulative article counter and dated activity events.

## Preview in the normal scorecard

1. Use the existing scorecard. Put provisional figures in the date column as display text, with an amber fill and a **Preview** date label. Use `0 so far` for a partial zero and leave comparisons and cumulative totals blank.
2. Put the current coverage window and the existing Doc link together in the coverage cell. Leave the closed-week highlights row for closed results. Add a separate view only when requested or useful for independent data, such as item-level evidence with a different scope.
3. After cutoff, keep the same date, remove the preview format and publish verified numbers, including verified zero. Clear unverified figures and name each missing source. Ordinary blank inputs are neutral, populated manual results are ice blue, and explicit pending or N/A cells are amber.

## Run the examples

Run these commands from the installed Skill folder. In the development repository, first change to `skills/weekly-product-review/`. For work in another project, copy this example into that project and use the installed script's absolute path; keep the installed example unchanged.

```bash
python examples/creator-wpr/collect_wpr.py --as-of 2027-02-12T17:15:00+01:00
python examples/creator-wpr/collect_wpr.py --input examples/creator-wpr/capture.partial-close.example.json --as-of 2027-02-05T17:10:00+01:00
python scripts/wpr_sync.py validate --wpr-dir examples/creator-wpr
python scripts/wpr_sync.py build --wpr-dir examples/creator-wpr --out-dir wpr-output
```

- The collector reads `capture.example.json` and prints candidate values. It never edits `metrics-data.md`, calls a service or publishes anything.
- The main fixture contains a complete capture. Its Markdown week starts as a preview. The partial-close fixture reproduces the older closed week with verified reach and zero outcomes, a stale visitor feed, and an article counter without a baseline. Use the `Capture / Coverage` and `Gap Reason` columns to carry the evidence into the review.
- `capture.example.json` gives account-wide reach, two typed posts and a linked article with its own counter. The article's lifetime total is not a weekly measure; the comparable difference is 27.
- Preview, stale and inaccessible captures return blank candidate values while retaining observed counts for diagnosis. Verified zero is a separate state. Existing closed history remains unchanged because collection is read-only.
- Preserve window and scope when dashboard labels look alike. The partial-close fixture keeps both reads of a rolling impressions total beside a separate since-publication count. It also records account and post-attributed profile viewers separately. These records stay outside the weekly candidate values.
- `metrics-data.md` keeps a pre-publication baseline outside the weekly series. It must not be used to fill missing weekly periods.
- Follow the [collector contract](../../references/collector-contract.md) for cutoff changes, timezone offsets, failed captures and scheduled retries. Scheduled execution needs project-specific setup; installing this skill does not create an automation.
