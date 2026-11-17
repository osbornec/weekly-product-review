# Metric Discovery Guide

Use this guide during **Mode 1 (Setup & Metric Discovery)** to choose high-signal metrics without getting stuck on instrumentation gaps.

## Discovery Rules

1. **Name the durable product or program, not one deliverable:** Never name the review after a single post, launch, or repo README heading. Ask what ongoing product or program is being run (e.g., *"Customer Education Programme"*, not the title of Week 1's post).
2. **Extract existing local baselines first:** Before interviewing the user for numbers, inspect existing project docs, trackers, changelogs, or CSVs to pre-fill what is already captured and pinpoint what lives externally.
3. **Right-size the metric count:**
   - **Most teams and solo builders:** Start lean with **7 to 10 metrics** so weekly capture takes under 5 minutes and the review stays sharp. Merge overlapping vanity counters (e.g., combine Reactions + Comments + Reposts into one engagement count) and skip derived ratio rows unless explicitly used for decisions.
   - **Business leaders (company-wide review):** Expand to **10 to 20 metrics** across growth, customer journey, delivery, and money/risk.

## Discovery Interview Flow

Ask 3–5 focused questions, propose a draft metric table + data-source map, then refine:

1. **Product & Stage:** What ongoing product or program does this review govern, who is the user/customer, and what is your current stage?
2. **User Lifecycle & Funnel:** Discover → sign up/buy → first value (activation) → repeat engagement → convert/retain or churn. What 1–2 numbers prove each step is healthy?
3. **Value Delivery:** What weekly operational activities create value? (e.g., articles published, deployments, onboarding time, uptime, support resolution).
4. **Money & Risk:** What drives revenue/opportunities, unit cost/time burn, quality defects, delivery failures (e.g., email bounces), or hiring capacity?
5. **Data Sources & Blind Spots:** Where does each number live today (local Markdown/CSV, web dashboard, Stripe, CRM, database)? Which 1–2 metrics aren't collected yet (Amber placeholders with ETAs)?

---

## Metric Menus by Archetype

Use these as starting menus—never dump every row blindly.

### 1. Solo Creator / Content & Outreach Pipeline (Lean 7–9 Metrics)
- **Publishing (Delivery):** Articles / Posts Published
- **Reach & Authority:** Content Impressions (weekly 7d total), Article Views (exact platform label), Social Engagements (combined reactions + comments + reposts + saves), Profile Views (Past 7 days)
- **Outreach & Pipeline:** Outbound Messages Sent, Conversations Started (substantive 1:1 replies + inbound)
- **Outcomes:** Intro Meetings Booked / Held, Concrete Opportunities (paid mandates, FTE roles, speaking invites)

### 2. B2B SaaS / Software Product
- **Headline / Growth:** New Signups/Orgs, Weekly Active Users (WAU) or DAU, Net New ARR / MRR
- **Customer Journey:** Website Visits, Trial/Demo Requests, Activation Rate (% completing setup within 7d), Weekly Retained Teams, Churn / Cancellations
- **Delivery & Quality:** P1/P2 Incidents, Median Support Resolution Time, Onboarding Time-to-Value (days), Uptime %
- **Money & Risk:** Cash Burn / Gross Margin, CAC / Paid Spend, Overdue Invoices, Open Critical Roles

### 3. Consumer / Mobile App / Freemium
- **Headline / Growth:** New Users, Total Users, DAU / WAU, WoW Active User Growth
- **Customer Journey:** Store/Landing Visits, Install-to-Signup %, Week-1 Activation %, Core Actions per User, Paid Conversion %
- **Delivery & Quality:** Crash-Free Sessions %, P95 Latency, Support Tickets per 1k WAU
- **Money & Risk:** Weekly Gross Revenue, Ad Spend / Blended CPI, Refund Rate

### 4. E-Commerce / Marketplace
- **Headline / Growth:** GMV / Orders, New Buyers, Repeat Buyers
- **Customer Journey:** Sessions, Add-to-Cart %, Checkout Conversion %, Repeat Purchase Rate
- **Delivery & Quality:** On-Time Fulfillment %, Delivery Lead Time, Return / Defect Rate, Stockouts
- **Money & Risk:** Gross Margin %, Paid ROAS / CAC, Support Contacts per Order

### 5. Internal Platform / Engineering Team (Inside Larger Org)
- **Upstream (Before You):** Incoming Intake Requests, Upstream Dependency Delays
- **Customer Journey (Internal Users):** Active Adopting Teams, Self-Serve Onboarding %, Core Workflows Run
- **Delivery & Quality:** Lead Time for Changes, Deployment Success %, Incidents / MTTR, Support Questions
- **Money & Risk:** Infra Spend per Unit, Security SLA Compliance %, Open Headcount

---

## Stand-In & Placeholder Patterns (Amber Cells)

Never delay launching a Weekly Product Review waiting for instrumentation:
- **Stand-ins:** Weekly repeat usage or complaint rate instead of NPS; qualified calls instead of pipeline value.
- **Amber Placeholder:** Set `type: not-collected`, include `ETA: YYYY-MM-DD`, and assign an owner to turn it Ice Blue or Zinc.
