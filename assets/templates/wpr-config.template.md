# WPR Config

## Metadata
- **Product / Program Name**: <Durable Product or Program Name>
- **Year**: 2026
- **Week Ending Day**: Friday
- **Meeting Cadence**: Mondays 09:00 (60 mins)
- **Owners / Attendees**: <PM, Engineering, Design, Growth, Support>
- **Style**: standard
- **Google Sheet ID**: 
- **Google Doc ID**: 
- **Google Sheet URL**: 
- **Google Doc URL**: 

## Product Machine Map
- **Customer Journey**: <Find -> Sign up/Buy -> Activate -> Engage -> Retain/Expand or Churn>
- **Value Delivery**: <Core operational and product activities that deliver value>
- **Money & Risk**: <Revenue, cost/burn, quality, support load, compliance/risk>
- **OKR Boundary**: <Current quarterly OKRs vs. day-to-day Weekly Product Review coverage>

## Metric Catalog

| Section | ID | Metric | Type | Format | Target | Analyses | Formula | Owner | Source / ETA |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| User Growth | new_users | New Users | manual | int | Q1: 20; 25 | qtd_sum, wow | | Growth | Analytics signup count |
| User Growth | total_users | Total Users | calculated | int | | | cumsum:new_users | Auto | Cumulative sum of New Users |
| User Growth | active_users | Weekly Active Users | manual | int | 100 | wow, rolling_4w, yoy | | Product | Product analytics (Fri) |
| Customer Journey | landing_visits | Landing Page Visits | manual | int | 2000 | rolling_4w, vs_prior_q | | Marketing | Web analytics |
| Customer Journey | activation_rate | Activation Rate | manual | percent | 0.40 | vs_target | | Product | % completing onboarding |
| Revenue | weekly_revenue | Weekly Revenue | manual | currency | 1500 | qtd_sum, wow | | Finance | Billing / Stripe |
| Money & Risk | customer_nps | Customer NPS | not-collected | float | 45 | | | Support | ETA: 2026-12-31 |

## Data Sources

| Metric IDs | Source System | Location / URL / Query | Date-Range Filter | Method | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| new_users, active_users | Product Analytics | Dashboard / API | Past 7 days | local-script | Aggregated via wpr/collect_wpr.py |
| weekly_revenue | Billing | Weekly revenue export | Past 7 days | csv-export | Or Stripe API |

## Metric & Target Changelog

| Effective Date | Metric ID | Change Type | Old -> New | Reason |
| :--- | :--- | :--- | :--- | :--- |
| | | | | |
