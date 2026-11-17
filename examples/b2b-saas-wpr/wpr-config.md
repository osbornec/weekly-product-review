# WPR Config (Sample B2B SaaS)

> Note: Sample placeholder product and numbers for demonstration purposes.

## Metadata
- **Product / Program Name**: Northstar Docs (Sample B2B SaaS)
- **Year**: 2026
- **Week Ending Day**: Friday
- **Meeting Cadence**: Mondays 09:00 UTC (60 mins)
- **Owners / Attendees**: PM, Engineering, Design, Growth, Support
- **Style**: standard
- **Google Sheet ID**: 
- **Google Doc ID**: 
- **Google Sheet URL**: 
- **Google Doc URL**: 

## Product Machine Map
- **Customer Journey**: Landing visit -> Workspace signup -> Team invites first collaborator (activation) -> Weekly active workspaces -> Paid Pro upgrade -> Renew or churn
- **Value Delivery**: Fast editor load times, reliable real-time sync, <4h support response
- **Money & Risk**: Net new MRR, churned MRR, P1 incidents, support backlog
- **OKR Boundary**: Q4 OKR covers SSO launch; Weekly Product Review monitors weekly acquisition, activation, retention, and support health.

## Metric Catalog

| Section | ID | Metric | Type | Format | Target | Analyses | Formula | Owner | Source / ETA |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Growth | new_workspaces | New Workspaces | manual | int | Q1: 25; Q4 26: 45; 35 | qtd_sum, wow | | Growth | Postgres signup query |
| Growth | total_workspaces | Total Workspaces | calculated | int | | | cumsum:new_workspaces | Auto | Cumulative sum |
| Customer Journey | landing_visits | Landing Page Visits | manual | int | 3000 | wow, rolling_4w | | Growth | Plausible weekly export |
| Customer Journey | activation_rate | 7-Day Activation Rate | manual | percent | 0.42 | vs_target | | Product | % inviting >=1 teammate |
| Customer Journey | wau_workspaces | Weekly Active Workspaces | manual | int | 140 | wow, rolling_4w, vs_prior_q | | Product | App telemetry (Fri) |
| Delivery & Quality | median_support_hrs | Median Support Response (hrs) | manual | float | 4.0 | vs_target | | Support | Helpdesk export |
| Revenue & Risk | net_new_mrr | Net New MRR ($) | manual | currency | 2500 | qtd_sum, wow | | Finance | Stripe weekly report |
| Revenue & Risk | logo_churn | Churned Workspaces | manual | int | 2 | wow | | Support | Stripe cancellations |
| Revenue & Risk | customer_nps | Customer NPS | not-collected | float | 45 | | | Support | ETA: 2026-12-15 |

## Data Sources

| Metric IDs | Source System | Location / URL / Query | Date-Range Filter | Method | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| new_workspaces, wau_workspaces | App Postgres | `analytics/weekly_workspaces.sql` | Trailing 7 days (UTC) | local-script | Run via collect_wpr.py |
| landing_visits | Plausible | Site overview -> Weekly CSV | Past 7 days | csv-export | Export every Friday |
| net_new_mrr, logo_churn | Stripe | Billing -> MRR movements | Past 7 days | api/mcp | Pull Friday 15:00 UTC |

## Metric & Target Changelog

| Effective Date | Metric ID | Change Type | Old -> New | Reason |
| :--- | :--- | :--- | :--- | :--- |
| 2026-10-02 | new_workspaces | Target Updated | 35 -> 45 | Q4 outbound launch |
