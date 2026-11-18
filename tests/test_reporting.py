"""Calendar-aligned reporting scenarios using invented operating data."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from test_metrics_writes import wpr


def metric(metric_id="units", formula="", analyses=None):
    return wpr.MetricDef("Operations", metric_id, metric_id.title(), "calculated" if formula else "manual",
                         "float", "", analyses or ["wow", "rolling_4w"], formula, "Team", "Synthetic")


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

    def test_preview_sheet_values_and_comparisons_are_unavailable(self):
        cfg = wpr.WPRConfig(metrics=[metric()])
        row = entry("2027-02-12", 40, state="preview")
        dates = wpr.dates_for_year(2027, "Friday")[1]
        grid, rows = wpr.build_sheet_grid(cfg, "Q1 27", dates, {row.week_date: row}, None, None, None, None, [], {})
        idx = dates.index(row.week_date) + 2
        self.assertIsNone(grid[rows["units"] - 1][idx]["v"])
        self.assertEqual(grid[rows["units"]][idx]["v"], "N/A")

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
