# Synthetic weekly data

## Pre-publication baseline

An invented historical capture averaged 90 account impressions across a different chart window. Keep its window separate; it is not another Friday observation.

## Interim observations

This example includes provisional observations in the scorecard. Its separate completed capture illustrates 640 account-wide reach and 27 article views added. Reconcile the completed capture before closing the preview.

## Week 2027-02-12
- Period State: preview
- Comparison Group: weekly-cutoff-v1
- Coverage: 5 February after 17:00 to 11 February 2027 at 17:00 +01:00

| ID | Metric | Value | Status | Note |
| --- | --- | --- | --- | --- |
| pieces | Original Pieces | | automated | Pending reconciliation |
| weekly_reach | Weekly Account Reach | 570 | preview | Synthetic preview read |
| weekly_visitors | Weekly Account Visitors | | automated | Pending reconciliation |
| article_growth | Article Views Added | | automated | Counter difference requires matched item and boundary captures |
| attempts | Campaign Attempts | | automated | Include dated bounce and resend attempts separately |
| responses | Substantive Respondents | | automated | Distinct person IDs only |
| meetings | Meetings Confirmed | | automated | Rescheduling does not add a meeting |
| outcomes | Outcomes Accepted | 0 | preview | No outcomes observed through the preview coverage end |

## Week 2027-02-05
- Period State: closed
- Comparison Group: weekly-cutoff-v1
- Coverage: 29 January to 5 February 2027, 17:00 +01:00 cutoff
- Missing Sources: Visitor feed stopped before cutoff. The article has no comparable opening snapshot.

| ID | Metric | Value | Status | Note | Capture / Coverage | Gap Reason |
| --- | --- | --- | --- | --- | --- | --- |
| pieces | Original Pieces | 1 | automated | Synthetic activity log | 5 Feb 17:10 +01:00, through 5 Feb 17:00 | |
| weekly_reach | Weekly Account Reach | 250 | automated | Synthetic account reach export | 5 Feb 17:06 +01:00, through 5 Feb 17:00 | |
| weekly_visitors | Weekly Account Visitors | | stale | Synthetic visitor feed observed 18 | 5 Feb 17:08 +01:00, through 4 Feb 17:00 | |
| article_growth | Article Views Added | | unavailable | Closing lifetime counter is 118 | 5 Feb 17:10 +01:00, closing counter at 5 Feb 17:00 | Missing comparable baseline |
| attempts | Campaign Attempts | 4 | automated | Synthetic activity log | 5 Feb 17:10 +01:00, through 5 Feb 17:00 | |
| responses | Substantive Respondents | 1 | automated | Synthetic activity log | 5 Feb 17:10 +01:00, through 5 Feb 17:00 | |
| meetings | Meetings Confirmed | 0 | verified-zero | Complete fixture coverage | 5 Feb 17:10 +01:00, through 5 Feb 17:00 | |
| outcomes | Outcomes Accepted | 0 | verified-zero | Complete fixture coverage | 5 Feb 17:10 +01:00, through 5 Feb 17:00 | |
