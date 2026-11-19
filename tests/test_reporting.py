"""Calendar-aligned reporting scenarios using invented operating data."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from test_metrics_writes import wpr


def metric(metric_id="units", formula="", analyses=None, fmt="float"):
    return wpr.MetricDef("Operations", metric_id, metric_id.title(), "calculated" if formula else "manual",
                         fmt, "", ["wow", "rolling_4w"] if analyses is None else analyses, formula, "Team", "Synthetic")


def entry(date, value, state="closed", group="", status="manual"):
    return wpr.WeekEntry(dt.date.fromisoformat(date),
                         {"units": wpr.WeekCell("units", "Units", str(value) if value is not None else "", value, status, "")},
                         state, group)


class ReportingTests(unittest.TestCase):
    def test_display_rounding_matches_spreadsheet_halfway_values(self):
        self.assertEqual(wpr.format_val(140.25, "float"), "140.3")
        self.assertEqual(wpr.format_val(2312.5, "currency"), "$2,313")
        self.assertEqual(wpr.format_val(-2.25, "float"), "-2.3")

    def stats(self, entries):
        cfg = wpr.WPRConfig(metrics=[metric()], style="no-em-dash")
        vals = wpr.evaluate_metric_series(cfg, sorted(entries, key=lambda e: e.week_date))
        return wpr.period_statistics({e.week_date: e for e in entries}, vals, entries[0].week_date, "units")

    def test_gap_is_not_week_over_week_or_four_week_average(self):
        rows = [entry("2027-02-12", 40), entry("2027-01-29", 20), entry("2027-01-22", 30), entry("2027-01-08", 10)]
        self.assertEqual(self.stats(rows), (None, None, None))

    def test_four_consecutive_periods_include_zero(self):
        rows = [entry("2027-02-12", 40), entry("2027-02-05", 20), entry("2027-01-29", 0), entry("2027-01-22", 12)]
        self.assertEqual(self.stats(rows), (20, 1, 18))

    def test_zero_prior_has_no_percentage_change(self):
        self.assertEqual(self.stats([entry("2027-02-12", 40), entry("2027-02-05", 0)]), (0, None, None))

    def test_preview_stale_and_unavailable_do_not_enter_comparisons(self):
        for status in ("preview", "stale", "unavailable"):
            with self.subTest(status=status):
                rows = [entry("2027-02-12", 40), entry("2027-02-05", 20, status=status)]
                self.assertEqual(self.stats(rows), (None, None, None))
        self.assertEqual(self.stats([entry("2027-02-12", 40, state="preview"), entry("2027-02-05", 20)])[1:], (None, None))

    def test_closed_period_keeps_verified_zero_beside_unavailable_metric(self):
        cfg = wpr.WPRConfig(metrics=[metric(), metric("latency")])
        current = entry("2027-02-12", 0, status="verified-zero")
        current.cells["latency"] = wpr.WeekCell("latency", "Latency", "", None, "unavailable", "Source offline")
        values = wpr.evaluate_metric_series(cfg, [current])
        self.assertEqual(values[current.week_date, "units"], 0)
        self.assertIsNone(values[current.week_date, "latency"])
        dates = wpr.dates_for_year(2027, "Friday")[1]
        grid, rows = wpr.build_sheet_grid(cfg, "Q1 27", dates, {current.week_date: current}, None, None, None, None, [], {})
        column = dates.index(current.week_date) + 2
        self.assertEqual(grid[rows["units"] - 1][column]["v"], 0)
        self.assertIsNone(grid[rows["latency"] - 1][column]["v"])

    def test_missing_automated_and_calculated_values_never_signal_on_track(self):
        automated = metric()
        automated.mtype = "automated"
        automated.target_raw = "10"
        cfg = wpr.WPRConfig(metrics=[automated, metric("rate", formula="ratio:units/units")])
        current = entry("2027-02-12", None, status="unavailable")
        values = wpr.evaluate_metric_series(cfg, [current])
        with tempfile.TemporaryDirectory() as temp:
            markdown, _ = wpr.generate_review_brief(cfg, [current], values, Path(temp))
        rows = [line for line in markdown.splitlines() if line.startswith(("| Operations | Units |", "| Operations | Rate |"))]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(wpr._markdown_cells(line)[7] == "Unavailable" for line in rows))
        self.assertNotIn("On track", markdown)

    def test_changed_comparison_group_breaks_comparability(self):
        rows = [entry("2027-02-12", 40, group="new-window"), entry("2027-02-05", 20, group="old-window")]
        self.assertEqual(self.stats(rows), (None, None, None))

    def test_week_over_week_crosses_year(self):
        self.assertEqual(self.stats([entry("2027-01-01", 40), entry("2026-12-25", 20)])[:2], (20, 1))

    def test_sheet_formulas_require_complete_windows_and_cross_quarter(self):
        cfg = wpr.WPRConfig(metrics=[metric()])
        dates = wpr.dates_for_year(2027, "Friday")
        current = entry("2027-04-02", 40)
        grid, rows = wpr.build_sheet_grid(cfg, "Q2 27", dates[2], {current.week_date: current}, "Q1 27", dates[1], None, None, [], {})
        idx = dates[2].index(dt.date(2027, 4, 2)) + 2
        average = grid[rows["units"] + 1][idx]["f"]
        self.assertIn("COUNT(", average)
        self.assertIn('<>4,"N/A"', average)
        self.assertIn("'Q1 27'!", average)

    def test_preview_scorecard_displays_text_then_closes_to_verified_numbers(self):
        source = metric("feed", analyses=[], fmt="int")
        source.mtype = "automated"
        cfg = wpr.WPRConfig(doc_url="https://example.test/reviews", metrics=[
            metric(analyses=["wow", "rolling_4w", "qtd_sum"]),
            metric("zero", analyses=[], fmt="int"), metric("missing", analyses=[], fmt="currency"),
            metric("blank", analyses=[], fmt="percent"), metric("running", "cumsum:units", analyses=[]), source,
        ])
        row = entry("2027-02-12", 40, state="preview")
        row.coverage = "6–11 February 2027"
        row.missing_sources = "Synthetic service export"
        row.cells["zero"] = wpr.WeekCell("zero", "Zero", "0", 0, "preview", "")
        row.cells["missing"] = wpr.WeekCell("missing", "Missing", "", None, "unavailable", "")
        row.cells["feed"] = wpr.WeekCell("feed", "Feed", "9", 9, "automated", "")
        dates = wpr.dates_for_year(2027, "Friday")[1]
        date = row.week_date.isoformat()
        def build():
            return wpr.build_sheet_grid(cfg, "Q1 27", dates, {row.week_date: row}, None, None, None, None, [],
                                        {row.week_date: "Reviewed highlight"})
        grid, rows = build()
        idx = dates.index(row.week_date) + 2
        units, zero, missing, blank = (rows[name] - 1 for name in ("units", "zero", "missing", "blank"))
        self.assertEqual(grid[units][idx]["v"], "40.0 (preview)")
        self.assertEqual(grid[zero][idx]["v"], "0 so far")
        self.assertEqual(grid[missing][idx]["v"], "Pending (preview)")
        self.assertEqual(grid[units][idx]["fill"], wpr.FILL_AMBER_PENDING)
        self.assertEqual(grid[missing][idx]["fill"], wpr.FILL_AMBER_PENDING)
        self.assertEqual(grid[blank][idx]["fill"], wpr.FILL_LEGEND_BG)
        for analysis in grid[units + 1:units + 4]:
            self.assertIsNone(analysis[idx]["v"])
            self.assertIsNone(analysis[idx]["f"])
        self.assertIsNone(wpr.evaluate_metric_series(cfg, [row])[row.week_date, "units"])
        self.assertIsNone(grid[rows["running"] - 1][idx]["f"])
        self.assertIsNone(grid[-1][idx]["v"])
        self.assertEqual(sum("https://example.test/reviews" in str(c) for c in (r[idx] for r in grid)), 1)
        self.assertTrue(any(row.coverage in (r[idx]["f"] or "") for r in grid))
        role = {"kind": "quarter", "year": row.week_date.year, "quarter": 1}
        preview = wpr.grid_to_payload(grid, dates, role)
        column = preview["week_columns"][date]
        def payload(tab):
            return {"row_signature": "layout", "catalog_signature": "catalog", "tabs": {"Synthetic scorecard": tab}}
        plan = wpr.plan_sync(payload(preview), payload(preview), date)["tabs"][0]
        self.assertEqual(plan["sheet_role"], role)
        self.assertEqual(plan["row_layout"]["metrics"], rows)
        roles = plan["row_layout"]["roles"]
        self.assertEqual(plan["coverage_cell"], f"{column}{roles['coverage']}")
        self.assertEqual(plan["notes_cell"], f"{column}{roles['closed_highlights']}")
        self.assertNotEqual(plan["coverage_cell"], plan["notes_cell"])
        self.assertIn(f"{column}{units + 1}", plan["text_cells"])
        self.assertIn("Preview", plan["date_header"]["number_format"])
        self.assertEqual(plan["number_formats"], {})
        row.period_state = "closed"
        row.cells["zero"].status = "verified-zero"
        closed, _ = build()
        self.assertEqual(closed[units][idx]["v"], 40)
        self.assertEqual(closed[units][idx]["fill"], wpr.FILL_ICE_MANUAL)
        self.assertEqual(closed[zero][idx]["v"], 0)
        self.assertEqual(closed[zero][idx]["fill"], wpr.FILL_ICE_MANUAL)
        self.assertEqual(closed[rows["feed"] - 1][idx]["v"], 9)
        self.assertEqual(closed[rows["feed"] - 1][idx]["fill"], wpr.FILL_ZINC_CALC)
        self.assertIsNone(closed[missing][idx]["v"])
        self.assertEqual(closed[blank][idx]["fill"], wpr.FILL_LEGEND_BG)
        self.assertEqual(closed[-1][idx]["v"], "Reviewed highlight")
        self.assertIn("ISNUMBER", closed[units + 3][idx]["f"])
        self.assertIn("ISNUMBER", closed[rows["running"] - 1][idx]["f"])
        close_plan = wpr.plan_sync(payload(wpr.grid_to_payload(closed, dates, role)), payload(preview), date)["tabs"][0]
        self.assertEqual(close_plan["text_cells"], [])
        self.assertEqual(close_plan["date_header"]["number_format"], "mmm dd")
        self.assertIn(f"{column}{zero + 1}", close_plan["number_cells"])
        self.assertEqual(close_plan["number_formats"], {
            f"{column}{units + 1}": {"type": "NUMBER", "pattern": "#,##0.0"},
            f"{column}{units + 2}": {"type": "PERCENT", "pattern": "0.0%"},
            f"{column}{units + 3}": {"type": "NUMBER", "pattern": "#,##0.0"},
            f"{column}{units + 4}": {"type": "NUMBER", "pattern": "#,##0.0"},
            f"{column}{rows['running']}": {"type": "NUMBER", "pattern": "#,##0.0"},
            f"{column}{zero + 1}": {"type": "NUMBER", "pattern": "#,##0"},
            f"{column}{missing + 1}": {"type": "CURRENCY", "pattern": "$#,##0"},
            f"{column}{blank + 1}": {"type": "PERCENT", "pattern": "0.0%"},
            f"{column}{rows['feed']}": {"type": "NUMBER", "pattern": "#,##0"},
        })
        self.assertIn("Synthetic service export", str(close_plan["writes"]))

    def test_generated_review_preserves_heading_on_close_and_names_missing_sources(self):
        cfg = wpr.WPRConfig(metrics=[metric()])
        row = entry("2027-02-12", 40, state="preview")
        row.coverage = "6–11 February 2027"
        row.missing_sources = "Synthetic source"
        with tempfile.TemporaryDirectory() as temp:
            def render():
                return wpr.generate_review_brief(cfg, [row], wpr.evaluate_metric_series(cfg, [row]), Path(temp))[0]
            preview = render()
            row.period_state = "closed"
            closed = render()
        self.assertEqual(preview.splitlines()[0], "# Week ending 12 February 2027")
        self.assertEqual(closed.splitlines()[0], preview.splitlines()[0])
        self.assertIn("- **Period State:** Preview", preview)
        self.assertIn("- **Period State:** Closed", closed)
        self.assertIn("- **Missing Sources:** Synthetic source", closed)

    def test_brief_reports_gap_as_unavailable(self):
        rows = [entry("2027-02-12", 40), entry("2027-01-29", 20)]
        cfg = wpr.WPRConfig(metrics=[metric()], style="no-em-dash")
        vals = wpr.evaluate_metric_series(cfg, list(reversed(rows)))
        with tempfile.TemporaryDirectory() as tmp:
            md, _ = wpr.generate_review_brief(cfg, rows, vals, Path(tmp))
        self.assertIn("| Operations | Units | 40.0 | - | - | - |", md)
        self.assertNotIn("+100.0%", md)

    def test_simple_raw_formula_computes_in_brief_values(self):
        cfg = wpr.WPRConfig(metrics=[metric(), metric("double", "={col}9*2+1")])
        row = entry("2027-02-12", 8)
        values = wpr.evaluate_metric_series(cfg, [row])
        self.assertEqual(values[row.week_date, "double"], 17)

    def test_raw_formula_can_reference_later_metric_without_code_execution(self):
        cfg = wpr.WPRConfig(metrics=[metric("double", "={col}13*2"), metric()])
        row = entry("2027-02-12", 8)
        self.assertEqual(wpr.evaluate_metric_series(cfg, [row])[row.week_date, "double"], 16)
        self.assertIsNone(wpr.safe_arithmetic("=__import__('os').getcwd()", lambda r: 8))
        self.assertIsNone(wpr.safe_arithmetic("={col}9/0", lambda r: 8))

    def test_raw_formula_missing_reference_is_unavailable(self):
        self.assertIsNone(wpr.safe_arithmetic("={col}999+1", lambda r: None))

    def test_cumulative_metric_does_not_reset_between_years(self):
        cfg = wpr.WPRConfig(metrics=[metric("running", "cumsum:units"), metric()])
        rows = [entry("2026-12-25", 5), entry("2027-01-01", 8)]
        vals = wpr.evaluate_metric_series(cfg, rows)
        self.assertEqual(vals[rows[-1].week_date, "running"], 13)

    def test_future_cells_are_neutral_and_legend_is_in_frozen_columns(self):
        cfg = wpr.WPRConfig(metrics=[metric()])
        current = entry("2027-02-12", 40)
        dates = wpr.dates_for_year(2027, "Friday")[1]
        grid, rows = wpr.build_sheet_grid(cfg, "Q1 27", dates, {current.week_date: current}, None, None, None, None, [], {})
        self.assertEqual(grid[rows["units"] - 1][2]["fill"], wpr.FILL_LEGEND_BG)
        self.assertIsNone(grid[rows["units"]][2]["f"])
        self.assertIn("Blue: manual", grid[5][0]["v"])
        self.assertIsNone(grid[5][2]["v"])


if __name__ == "__main__":
    unittest.main()
