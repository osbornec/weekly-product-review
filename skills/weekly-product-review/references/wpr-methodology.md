# Weekly Product Review Methodology

A weekly review for product builders and teams. Keep the records in Markdown and sync them to Google Sheets and Docs when needed.

## Why Run a Weekly Cadence

- **Review changes while the work is fresh.** Check onboarding, activation and retention at the configured weekly cutoff. Compare what moved with what shipped and which users were affected.
- **Keep one cross-functional scorecard:** Product, engineering, design, growth, and support examine the full lifecycle in one ledger instead of isolated team dashboards. Seeing upstream traffic, activation, support load, and churn side by side prevents silent handoff gaps.
- **Investigate likely drivers.** Use a flow, channel or cohort split to see where a change is concentrated. Check the result against customer evidence before assigning a cause.

## Two Core Inputs

1. **Quantitative Scorecard:** Track 7 to 10 core metrics for focused teams or solo builders (or 10 to 20 for multi-function leadership leads) in a flexible rolling sheet.
2. **Qualitative Verbatims:** Pull 1 to 3 raw user quotes from support tickets, session replays, sales calls, or customer replies each week.

> **Why customer quotes sit beside metrics:** Aggregate averages hide localized failures. If customer feedback contradicts an overall trend, treat that tension as a diagnostic clue and split the metric by segment (plan, device, region, acquisition source, or feature usage).

## Five-Stage Weekly Loop

1. **Map Product Flow and Select Metrics (7–10 default):**
   - Trace the system from first touch to durable value: User discovery and onboarding -> Core value delivery -> Revenue, unit economics, and operational risk.
   - Include upstream dependencies and downstream quality signals that users experience directly.
   - Do not wait for full analytics coverage before starting: insert an **Amber** placeholder (`ETA: <date>`) or an observable proxy (such as weekly repeat usage before formal NPS surveys exist).
   - Confirm the scorecard with peers so everyone agrees it models how users actually experience the product.
2. **Build the Rolling Ledger:**
   - Keep newer calendar dates on the left. Find the reporting week by its date, since future weeks can precede it.
   - Use ice blue for populated manual inputs, zinc for calculated or automated results, amber for explicit previews, pending and `N/A`, and a neutral fill for ordinary blanks.
   - Include rolling 4-week averages only for four consecutive, comparable closed observations. A missing week makes the comparison unavailable; zero remains valid. Keep previews and differently windowed historical baselines outside those calculations. Include QTD/YTD totals, exact-date weekly deltas and prior-year seasonal comparisons where appropriate.
3. **Review with Metric Owners:**
   - Invite the people who can explain the inputs and act on what changed. For a solo review, check the source records and carry-over actions before deciding what to do.
4. **Inspect Variance, Then Split:**
   - Skip line-by-line recitations and focus on anomalies (`>= 20%` WoW moves, target misses, or sudden support spikes):
     1. Was this move expected from recent launches, or unexplained?
     2. Does the shift hold against the 4-week rolling average?
     3. Which controllable input moved it, and what segment split (`platform`, `plan`, `cohort`, or `feature`) tests the hypothesis?
   - When the current grid cannot explain a movement, update `wpr/wpr-config.md` to add a segment split or new metric.
5. **Commit Two-Track Actions:**
   - **Track 1 — Instrumentation & Ledger:** New metrics, segment splits, automated collectors, or promoting Amber placeholders into automated inputs.
   - **Track 2 — Product & Workflow:** Bug fixes, onboarding improvements, UX updates, pricing/packaging tweaks, or direct customer outreach.
   - Assign **Action + Owner + Due Date** to every item and review carry-over status at the top of next week's session.

## Cadence & Timebox

- **Cross-functional product teams:** **30 to 60 minutes** weekly focused on anomalies, customer feedback, and assigned next steps.
- **Solo builders / creators:** **15 to 30 minutes** weekly (e.g., Friday afternoon) combining automated collector pulls, user replies, and next week's build/distribution priorities.

## Weekly Product Review vs. Quarterly Planning

- **Quarterly planning (such as OKRs)** governs your 2 to 3 deliberate strategic bets for the quarter.
- **Weekly Product Review** governs baseline operational health across uptime, onboarding, support load, revenue, and retention so core systems stay healthy between quarterly cycles.
- Use the weekly history as evidence when setting the next quarter's targets.
