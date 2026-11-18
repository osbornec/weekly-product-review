# Collector contract

Use this contract when building a project-specific collector. See [the synthetic creator example](../examples/creator-wpr/README.md) for a runnable implementation.

## Capture and period fields

| Field | Meaning |
| --- | --- |
| `metric_id`, `scope`, `unit` | Stable identity, population measured and unit. Account reach, one item's reach and an article counter are different observations. |
| `period_start_exclusive`, `period_end_inclusive` | Exact reporting boundaries as ISO timestamps with UTC offsets. Never infer a year or timezone from status prose. |
| `time_zone` | Named reporting timezone. Store the actual offset at each boundary, including daylight-saving transitions. |
| `captured_at`, `coverage_through` | When the source was checked and how far its evidence extends. A recent capture does not establish complete coverage. |
| `source`, `source_label` | Exact query, export or dashboard and its displayed label. Preserve its actual window when it differs from the reporting cutoff. |
| `state` | `preview`, `verified`, `verified-zero`, `unavailable` or `stale`. |
| `comparison_group` | A versioned period/definition identifier. Change it when the cutoff, population or counting rule changes; do not compare across groups automatically. |

## State rules

- A numeric zero requires checked coverage for the whole interval. Missing access, incomplete coverage and no returned rows do not establish zero.
- Show a partial observation in the usual scorecard cell as preview text. A count of zero within partial coverage is `0 so far`. Record the source window and capture time. At close, list any missing sources and publish verified values independently. For example, a warehouse review can close with 32 verified shipments and zero verified returns, while a stale carrier feed and a cumulative counter without a comparable baseline stay blank.
- Keep observations from an unfinished interval outside the closed weekly series. New weeks created by `add-week` have `Period State: preview`. After the cutoff, check each metric's evidence and mark the period `closed`: verified values may coexist with blank `unavailable` or `stale` cells. Missing access to one source does not make an independent, fully covered observation provisional. Never close a still-open interval or admit an unverified numeric value merely to display it.
- Legacy week tables without a period-state line are treated as closed for compatibility. Migrate genuinely provisional historical rows explicitly.
- Cell statuses `preview`, `unavailable` and `stale` do not contribute to calculations. `verified-zero` requires numeric zero. Keep the collection origin (`manual` or `automated`) in the source record.
- Stage candidate values without overwriting verified history. A failed recapture changes the capture log, not a previously verified weekly value. Corrections need a dated restatement and supporting evidence.
- For cumulative counters, calculate a difference only between comparable snapshots for the same item. A missing baseline is unavailable. A decrease requires investigation rather than an invented negative growth figure.
- Keep typed item rows separately: original post, article promotion and repost. Weekly item impressions and lifetime profile activity need distinct labels and windows. Item-level totals may overlap and must not replace an account-wide count.
- Record historical baselines with their own windows and source definitions. Never insert nonmatching historical windows into the Friday series merely to obtain four observations.

## Worked partial close and source windows

The [partial-close fixture](../examples/creator-wpr/capture.partial-close.example.json) closes the interval with mixed source coverage. Reconcile each source independently. Copy actual capture time and coverage into the matching metric row and name source gaps for the week.

| Metric | Close result | Capture and coverage |
| --- | --- | --- |
| Weekly Account Reach | 250 verified | 5 Feb 17:06 +01:00, covers cutoff at 17:00 |
| Outcomes Accepted | 0 verified | 5 Feb 17:10 +01:00, covers cutoff at 17:00 |
| Weekly Account Visitors | Blank, stale source | Checked 5 Feb 17:08 +01:00, coverage stops 4 Feb at 17:00 |
| Article Views Added | Blank, missing comparable baseline | Checked 5 Feb 17:10 +01:00. Closing counter is 118 at 17:00 |

The same fixture keeps separate item observations even when the source label is `Impressions`. The rolling-seven-day dashboard reports 214 at 17:03 and 218 at 17:09 with a partial final day. The detail view reports 225 since publication at 17:04. Retain each read's label, source, scope, window and capture time. Treat the changed count as a later observation of that window. Keep account profile viewers separate from post-attributed viewers. The collector returns these observations as evidence apart from the weekly candidates.

## Retry and close workflow

```mermaid
flowchart LR
    A[Collect dated evidence] --> B[Stage candidate values]
    B --> C{Reporting cutoff passed?}
    C -->|No| D[Log preview; preserve history]
    C -->|Yes| E[Close interval; reconcile verified metrics and mark gaps blank]
    E --> F[Validate and build]
    F --> G[Sync each destination and read back]
    G --> H[Record destination status]
    D --> A
```

- Browser sign-out, unavailable connectors and stale exports: log the source failure and last successful capture; leave unverified values blank.
- Retry the same period and destination identifiers. Do not add another weekly row or duplicate a dated review.
- Stop an individual run after one attempted refresh per failing source. Report what is pending and retry when access is restored; do not retry indefinitely or request broader permissions automatically.
- Track collection, Markdown reconciliation, Sheet sync and Doc sync independently. A successful Sheet update does not establish a successful Doc update.
- Candidate `state: verified` is a collection state, not a Markdown cell status. After verification, reconcile a nonzero automated value using cell status `automated`; use `verified-zero` for a verified zero. Keep the source evidence and collection state in the capture record.
- Persist project-local checkpoints and destination receipts as described in [partial completion](connector-sync.md#partial-completion). A failed readback stays pending; on a later run, read before resubmitting an uncertain write. Revalidate receipts when intended content changes.
