# Synthetic creator config

## Metadata
- **Product / Program Name**: Harbour Learning Journal (Synthetic)
- **Year**: 2027
- **Week Ending Day**: Friday
- **Meeting Cadence**: Friday after the reporting cutoff
- **Owners / Attendees**: Editorial team
- **Style**: no-em-dash

## Product Machine Map
- **Customer Journey**: Publish useful tutorials -> Readers visit -> Meaningful responses -> Meetings -> Confirmed outcomes
- **Value Delivery**: Original content and specific follow-up
- **Money & Risk**: Qualified outcomes, incomplete capture and duplicate counting

## Metric Catalog
| Section | ID | Metric | Type | Format | Target | Analyses | Formula | Owner | Source / ETA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Publishing | pieces | Original Pieces | automated | int | 1 | qtd_sum | | Editorial | Dated original publications |
| Reach | weekly_reach | Weekly Account Reach | automated | int | 500 | wow, rolling_4w | | Editorial | Exact-window account capture |
| Reach | weekly_visitors | Weekly Account Visitors | automated | int | 25 | wow, rolling_4w | | Editorial | Exact-window account capture |
| Reach | article_growth | Article Views Added | automated | int | 20 | wow | | Editorial | Difference of comparable article counters |
| Activity | attempts | Campaign Attempts | automated | int | 5 | qtd_sum | | Editorial | Dated events; bounces and resends are attempts |
| Activity | responses | Substantive Respondents | automated | int | 2 | wow | | Editorial | Unique synthetic person IDs |
| Outcomes | meetings | Meetings Confirmed | automated | int | 1 | qtd_sum | | Editorial | Unique synthetic meeting IDs |
| Outcomes | outcomes | Outcomes Accepted | automated | int | 1 | qtd_sum | | Editorial | Unique synthetic outcome IDs |

## Data Sources
| Metric IDs | Source System | Location / URL / Query | Date-Range Filter | Method | Notes |
| --- | --- | --- | --- | --- | --- |
| pieces, weekly_reach, weekly_visitors, article_growth, attempts, responses, meetings, outcomes | Invented capture fixture | capture.example.json | Explicit offset-aware start exclusive and end inclusive | local-script | Run collect_wpr.py; stage candidates and verify coverage before reconciliation |

## Metric & Target Changelog
| Effective Date | Metric ID | Change Type | Old -> New | Reason |
| --- | --- | --- | --- | --- |
