"""Typed inputs, stable identities and offline workbook round trips."""
import argparse
import contextlib
import io
import shutil
import unittest
from pathlib import Path
import test_metrics_writes as fixtures
from test_metrics_writes import SOURCE, wpr


class ImportValidationTests(unittest.TestCase):
    setUp = fixtures.MetricsWritesTest.setUp
    run_command = fixtures.MetricsWritesTest.run_command
    csv_input = fixtures.MetricsWritesTest.csv_input
    xlsx_input = fixtures.MetricsWritesTest.xlsx_input

    def test_wrong_weekday_add_is_rejected_without_changes(self):
        with self.assertRaisesRegex(ValueError, "must be a Friday"):
            self.run_command(wpr.cmd_add_week, date="2027-01-11", force=False)
        self.assertEqual(self.data.read_bytes(), SOURCE.encode())

    def test_invalid_numbers_are_rejected_before_import_write(self):
        for value in ("bogus", "nan", "inf", "1,2", "1.5", "12%", "1e500"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input(value)))
            self.assertEqual(self.data.read_bytes(), SOURCE.encode())

    def test_validator_detects_malformed_historical_value(self):
        self.data.write_bytes(SOURCE.replace("| 12 |", "| bogus |", 1).encode())
        errors, _ = wpr.validate_wpr(self.root)
        self.assertTrue(any("Invalid int" in error for error in errors))

    def test_validator_detects_wrong_historical_weekday(self):
        self.data.write_bytes(SOURCE.replace("2027-01-08", "2027-01-11").encode())
        errors, _ = wpr.validate_wpr(self.root)
        self.assertTrue(any("does not end on Friday" in error for error in errors))

    def test_validator_groups_missing_preview_inputs_and_closed_source_gaps(self):
        table = """# Weekly Metrics Data

## Week 2027-01-08
- Period State: {state}

| ID | Metric | Value | Status | Note | Gap Reason |
| --- | --- | --- | --- | --- | --- |
| shipments | Shipments | | {status} | | {reason} |
| latency | Latency | | {status} | | {reason} |
"""
        for state, status, reason, label in (
            ("preview", "manual", "", "Reporting period is open"),
            ("closed", "unavailable", "Missing comparable baseline", "Missing comparable baseline"),
            ("closed", "stale", "", "Stale source"),
            ("closed", "manual", "", "Pending manual input"),
        ):
            with self.subTest(state=state, status=status, reason=reason):
                self.data.write_text(table.format(state=state, status=status, reason=reason), encoding="utf-8")
                errors, warnings = wpr.validate_wpr(self.root)
                self.assertEqual(errors, [])
                newest = [warning for warning in warnings if warning.startswith("Newest week")]
                self.assertEqual(newest, [f"Newest week 2027-01-08: {label} (shipments, latency)."])

    def test_unknown_csv_label_is_reported_and_noop(self):
        output = self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13", label="Unknown measure")))
        self.assertIn("unmatched_rows: 1", output)
        self.assertEqual(self.data.read_bytes(), SOURCE.encode())

    def test_generated_workbook_imports_four_weeks_after_display_rename(self):
        source = self.root / "fixture"
        shutil.copytree(Path(__file__).resolve().parents[1] / "examples" / "b2b-saas-wpr", source)
        with contextlib.redirect_stdout(io.StringIO()):
            wpr.cmd_build(argparse.Namespace(wpr_dir=str(source), out_dir=str(self.root / "output"), active_tab_first=True, overwrite_review=False))
        self.data.write_bytes(b"# Weekly Metrics Data\n")
        config = (source / "wpr-config.md").read_text(encoding="utf-8")
        (self.root / "wpr-config.md").write_text(config.replace("New Workspaces", "New Customer Groups"), encoding="utf-8")
        output = self.run_command(wpr.cmd_import_xlsx, xlsx=str(self.root / "output" / "wpr-workbook.xlsx"))
        weeks = wpr.load_metrics_data(self.data)
        self.assertEqual(len(weeks), 4)
        self.assertEqual(weeks[0].cells["new_workspaces"].value_num, 48)
        self.assertEqual(weeks[0].cells["new_workspaces"].metric_name, "New Customer Groups")
        self.assertIn("uncomputed_headers: 0", output)

    def test_uncomputed_header_is_reported_without_writes(self):
        path = self.csv_input("13")
        path.write_text(path.read_text().replace("2027-01-08", "=UNCOMPUTED"))
        output = self.run_command(wpr.cmd_import_csv, csv=str(path))
        self.assertIn("uncomputed_headers: 1", output)
        self.assertEqual(self.data.read_bytes(), SOURCE.encode())

    def test_exported_preview_values_do_not_import_as_closed_observations(self):
        preview = SOURCE.replace("## Week 2027-01-08\n", "## Week 2027-01-08\n- Period State: preview\n")
        self.data.write_text(preview, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(wpr.cmd_build(argparse.Namespace(wpr_dir=self.root, out_dir=self.root / "output",
                                                             active_tab_first=True, overwrite_review=False)), 0)
        empty = b"# Weekly Metrics Data\n"
        self.data.write_bytes(empty)
        self.run_command(wpr.cmd_import_xlsx, xlsx=str(self.root / "output" / "wpr-workbook.xlsx"))
        self.assertEqual(self.data.read_bytes(), empty)
        self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("0 so far")))
        self.assertEqual(self.data.read_bytes(), empty)

    def test_invalid_last_value_does_not_partially_commit_first_value(self):
        path = self.csv_input("13")
        with path.open("a") as handle:
            handle.write("Latency,,bogus\n")
        with self.assertRaises(ValueError):
            self.run_command(wpr.cmd_import_csv, csv=str(path))
        self.assertEqual(self.data.read_bytes(), SOURCE.encode())


if __name__ == "__main__":
    unittest.main()
