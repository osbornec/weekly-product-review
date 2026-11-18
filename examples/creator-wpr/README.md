# Synthetic creator review

All names, URLs, figures and events in this example are invented. It demonstrates a publication programme with account-wide measurements, separate content items, a cumulative article counter and dated activity events.

```bash
python examples/creator-wpr/collect_wpr.py --as-of 2027-02-12T17:15:00+01:00
python scripts/wpr_sync.py validate --wpr-dir examples/creator-wpr
python scripts/wpr_sync.py build --wpr-dir examples/creator-wpr --out-dir wpr-output
```

- The collector reads `capture.example.json` and prints candidate values. It never edits `metrics-data.md`, calls a service or publishes anything.
- The fixture contains a complete capture. The Markdown starts with an open period to demonstrate reconciliation: check candidates, retain evidence, enter verified values, then set `Period State: closed`. Do not close a real period based only on this example.
- `capture.example.json` gives account-wide reach, two typed posts and a linked article with its own counter. The article's lifetime total is not a weekly measure; the comparable difference is 27.
- Preview, stale and inaccessible captures return blank candidate values while retaining observed counts for diagnosis. Verified zero is a separate state. Existing closed history remains unchanged because collection is read-only.
- `metrics-data.md` keeps a pre-publication baseline outside the weekly series. It must not be used to fill missing weekly periods.
- Follow the [collector contract](../../references/collector-contract.md) for cutoff changes, timezone offsets, failed captures and scheduled retries. Scheduled execution needs project-specific setup; installing this skill does not create an automation.
