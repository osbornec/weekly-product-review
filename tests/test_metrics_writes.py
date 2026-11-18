"""Synthetic regression cases for non-destructive metric updates."""

import argparse
import contextlib
import csv
import importlib.util
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "wpr_sync_under_test", Path(__file__).resolve().parents[1] / "skills" / "weekly-product-review" / "scripts" / "wpr_sync.py"
)
wpr = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wpr
SPEC.loader.exec_module(wpr)

CONFIG = """# Synthetic review

## Metadata
- **Year**: 2027
- **Week Ending Day**: Friday

## Metric Catalog
| Section | ID | Metric | Type | Format | Target | Analyses | Formula | Owner | Source / ETA |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Operations | shipments | Shipments | manual | int | 20 | wow | | Operations | Synthetic source |
| Operations | latency | Latency | manual | float | 3 | | | Operations | Synthetic source |
"""

SOURCE = """# Synthetic operating record

## Preview observations

Keep [preview evidence](https://example.test/preview).

| Observation | State |
| --- | --- |
| Open-period capture | Provisional |

## Week 2027-01-08
- Quarter: Q1 27 | Week of Quarter: 2 | Week of Year: 1

| ID | Metric | Value | Status | Note | Evidence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| shipments | Shipments | 12 | manual | Keep [source](https://example.test/proof) | Keep extra column |
| latency | Latency | 2.5 | manual | Keep latency note | |
| retired_metric | Historical metric | 77 | manual | Preserve uncatalogued row | |

### Historical source notes

Keep this paragraph and its [link](https://example.test/history).
"""


class MetricsWritesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wpr-synthetic-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "metrics-data.md"
        (self.root / "wpr-config.md").write_text(CONFIG, encoding="utf-8")
        self.data.write_bytes(SOURCE.encode("utf-8"))

    def run_command(self, command, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = command(argparse.Namespace(wpr_dir=str(self.root), **kwargs))
        self.assertEqual(result, 0, output.getvalue())
        return output.getvalue()

    def csv_input(self, value, label="Shipments"):
        path = self.root / "input.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows([["Friday", "", "2027-01-08"], [], [], [], [], [], [label, "", value]])
        return path

    def xlsx_input(self, value):
        path = self.root / "input.xlsx"
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        serial = wpr.excel_serial(wpr.dt.date(2027, 1, 8))
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "xl/workbook.xml",
                f'<workbook xmlns="{ns}" xmlns:r="{rel_ns}"><sheets>'
                '<sheet name="Q1 27" sheetId="1" r:id="rId1"/></sheets></workbook>',
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                f'<worksheet xmlns="{ns}"><sheetData>'
                '<row r="4"><c r="A4" t="inlineStr"><is><t>Friday</t></is></c>'
                f'<c r="C4"><v>{serial}</v></c></row>'
                '<row r="9"><c r="A9" t="inlineStr"><is><t>Shipments</t></is></c>'
                f'<c r="C9"><v>{value}</v></c></row></sheetData></worksheet>',
            )
        return path

    def test_add_week_preserves_original_content(self):
        self.run_command(wpr.cmd_add_week, date="2027-01-15", force=False)
        updated = self.data.read_text(encoding="utf-8")
        prefix, old_week = SOURCE.split("## Week 2027-01-08", 1)
        self.assertTrue(updated.startswith(prefix))
        self.assertIn("## Week 2027-01-15", updated)
        self.assertTrue(updated.endswith("## Week 2027-01-08" + old_week))
        self.assertEqual(len(wpr.load_metrics_data(self.data)), 2)

    def test_forced_reset_reopens_period_and_retains_comparison_group(self):
        original = SOURCE.replace("## Week 2027-01-08\n", "## Week 2027-01-08\n- Period State: closed\n- Comparison Group: window-v1\n")
        self.data.write_bytes(original.encode())
        self.run_command(wpr.cmd_add_week, date="2027-01-08", force=True)
        reset = wpr.load_metrics_data(self.data)[0]
        self.assertEqual(reset.period_state, "preview")
        self.assertEqual(reset.comparison_group, "window-v1")
        self.assertEqual(reset.cells["shipments"].value_raw, "")
        self.assertIn("Preserve uncatalogued row", self.data.read_text())

    def test_csv_changes_only_selected_cell(self):
        self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13")))
        self.assertEqual(self.data.read_bytes(), SOURCE.replace("| 12 |", "| 13 |", 1).encode())

    def test_xlsx_changes_only_selected_cell(self):
        self.run_command(wpr.cmd_import_xlsx, xlsx=str(self.xlsx_input("13")))
        self.assertEqual(self.data.read_bytes(), SOURCE.replace("| 12 |", "| 13 |", 1).encode())

    def test_csv_noop_keeps_bytes_and_does_not_replace_file(self):
        original = b"\xef\xbb\xbf" + SOURCE.replace("\n", "\r\n").encode()
        self.data.write_bytes(original)
        with mock.patch.object(wpr.os, "replace") as replace:
            self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("12")))
        replace.assert_not_called()
        self.assertEqual(self.data.read_bytes(), original)

    def test_xlsx_noop_keeps_bytes(self):
        original = self.data.read_bytes()
        self.run_command(wpr.cmd_import_xlsx, xlsx=str(self.xlsx_input("12")))
        self.assertEqual(self.data.read_bytes(), original)

    def test_csv_without_values_keeps_empty_file(self):
        self.data.write_bytes(b"")
        self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("")))
        self.assertEqual(self.data.read_bytes(), b"")

    def test_xlsx_without_values_keeps_empty_file(self):
        self.data.write_bytes(b"")
        self.run_command(wpr.cmd_import_xlsx, xlsx=str(self.xlsx_input("")))
        self.assertEqual(self.data.read_bytes(), b"")

    def test_changed_csv_preserves_bom_and_crlf(self):
        self.data.write_bytes(b"\xef\xbb\xbf" + SOURCE.replace("\n", "\r\n").encode())
        self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13")))
        expected = b"\xef\xbb\xbf" + SOURCE.replace("| 12 |", "| 13 |", 1).replace("\n", "\r\n").encode()
        self.assertEqual(self.data.read_bytes(), expected)

    def test_add_week_preserves_bom_and_crlf(self):
        self.data.write_bytes(b"\xef\xbb\xbf" + SOURCE.replace("\n", "\r\n").encode())
        self.run_command(wpr.cmd_add_week, date="2027-01-15", force=False)
        updated = self.data.read_bytes()
        self.assertTrue(updated.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", updated.replace(b"\r\n", b""))

    def test_csv_zero_is_written_without_losing_notes(self):
        self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("0")))
        self.assertEqual(self.data.read_bytes(), SOURCE.replace("| 12 |", "| 0 |", 1).encode())

    def test_add_week_dry_run_has_diff_and_keeps_file(self):
        output = self.run_command(wpr.cmd_add_week, date="2027-01-15", force=False, dry_run=True)
        self.assertIn("+## Week 2027-01-15", output)
        self.assertEqual(self.data.read_bytes(), SOURCE.encode())

    def test_csv_dry_run_has_diff_and_keeps_file(self):
        output = self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13")), dry_run=True)
        self.assertIn("+| shipments | Shipments | 13 |", output)
        self.assertEqual(self.data.read_bytes(), SOURCE.encode())

    def test_xlsx_dry_run_has_diff_and_keeps_file(self):
        output = self.run_command(wpr.cmd_import_xlsx, xlsx=str(self.xlsx_input("13")), dry_run=True)
        self.assertIn("+| shipments | Shipments | 13 |", output)
        self.assertEqual(self.data.read_bytes(), SOURCE.encode())

    def test_failed_replace_keeps_source_and_removes_temporary_file(self):
        with mock.patch.object(wpr.os, "replace", side_effect=OSError("Synthetic failure")):
            with self.assertRaises(OSError):
                self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13")))
        self.assertEqual(self.data.read_bytes(), SOURCE.encode())
        self.assertFalse(list(self.root.glob(".metrics-data.md.*.tmp")))

    def test_flush_failure_keeps_source_and_removes_temporary_file(self):
        with mock.patch.object(wpr.os, "fsync", side_effect=OSError("Synthetic flush failure")):
            with self.assertRaises(OSError):
                self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13")))
        self.assertEqual(self.data.read_bytes(), SOURCE.encode())
        self.assertFalse(list(self.root.glob(".metrics-data.md.*.tmp")))

    def test_atomic_replacement_receives_complete_file(self):
        actual_replace = wpr.os.replace
        observed = []

        def inspect_replace(source, destination):
            observed.append(Path(source).read_bytes())
            self.assertEqual(Path(destination).read_bytes(), SOURCE.encode())
            self.assertEqual(Path(source).parent, Path(destination).parent)
            actual_replace(source, destination)

        with mock.patch.object(wpr.os, "replace", side_effect=inspect_replace):
            self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13")))
        self.assertEqual(observed, [SOURCE.replace("| 12 |", "| 13 |", 1).encode()])

    def test_can_create_missing_data_file(self):
        self.data.unlink()
        self.run_command(wpr.cmd_add_week, date="2027-01-15", force=False)
        self.assertEqual(wpr.load_metrics_data(self.data)[0].week_date, wpr.dt.date(2027, 1, 15))

    def test_new_week_can_be_inserted_before_older_week(self):
        self.data.write_text(SOURCE.replace("2027-01-08", "2027-01-22"), encoding="utf-8")
        self.run_command(wpr.cmd_add_week, date="2027-01-15", force=False)
        weeks = wpr.load_metrics_data(self.data)
        self.assertEqual([e.week_date.day for e in weeks], [22, 15])
        self.assertIn("Preserve uncatalogued row", self.data.read_text(encoding="utf-8"))

    def test_add_week_keeps_custom_document_without_existing_weeks(self):
        custom = "# Synthetic project\n\nKeep this preview without a trailing newline."
        self.data.write_text(custom, encoding="utf-8")
        self.run_command(wpr.cmd_add_week, date="2027-01-15", force=False)
        self.assertTrue(self.data.read_text(encoding="utf-8").startswith(custom + "\n\n"))

    def test_noop_keeps_single_newlines_and_original_status_case(self):
        unusual = SOURCE.replace("\n\n## Week", "\n## Week").replace("| manual |", "| MANUAL |")
        self.data.write_bytes(unusual.encode())
        self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("12")))
        self.assertEqual(self.data.read_bytes(), unusual.encode())

    def test_changed_import_keeps_original_status_case(self):
        unusual = SOURCE.replace("| manual |", "| MANUAL |")
        self.data.write_bytes(unusual.encode())
        self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13")))
        self.assertEqual(self.data.read_bytes(), unusual.replace("| 12 |", "| 13 |", 1).encode())

    def test_escaped_pipe_in_note_survives_import(self):
        original = SOURCE.replace("Keep latency note", r"Keep a \| in this note")
        self.data.write_bytes(original.encode())
        self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13")))
        self.assertEqual(self.data.read_bytes(), original.replace("| 12 |", "| 13 |", 1).encode())

    def test_context_table_before_metric_table_is_preserved(self):
        context = "| Context | Value |\n| --- | --- |\n| Capture | Preview |\n\n"
        original = SOURCE.replace("| ID | Metric |", context + "| ID | Metric |", 1)
        self.data.write_bytes(original.encode())
        self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13")))
        self.assertEqual(self.data.read_bytes(), original.replace("| 12 |", "| 13 |", 1).encode())

    def test_import_adds_missing_metric_without_losing_other_content(self):
        row = "| latency | Latency | 2.5 | manual | Keep latency note | |\n"
        original = SOURCE.replace(row, "")
        self.data.write_bytes(original.encode())
        self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("3.5", label="Latency")))
        updated = self.data.read_text(encoding="utf-8")
        self.assertIn("| latency | Latency | 3.5 | manual |  |  |", updated)
        self.assertIn("Preserve uncatalogued row", updated)
        self.assertTrue(updated.endswith("### Historical source notes\n\nKeep this paragraph and its [link](https://example.test/history).\n"))

    def test_duplicate_week_is_rejected_without_writing(self):
        original = SOURCE + "\n## Week 2027-01-08\n\n| ID | Metric | Value | Status | Note |\n| --- | --- | --- | --- | --- |\n| shipments | Shipments | 1 | manual | |\n"
        self.data.write_bytes(original.encode())
        with self.assertRaisesRegex(ValueError, "Duplicate week"):
            self.run_command(wpr.cmd_add_week, date="2027-01-15", force=False)
        self.assertEqual(self.data.read_bytes(), original.encode())

    def test_duplicate_metric_is_rejected_without_writing(self):
        original = SOURCE.replace("### Historical", "| shipments | Shipments | 4 | manual | | |\n\n### Historical")
        # Keep both rows contiguous so they belong to the same metric table.
        original = original.replace("| |\n\n| shipments", "| |\n| shipments")
        self.data.write_bytes(original.encode())
        with self.assertRaisesRegex(ValueError, "Duplicate metric row"):
            self.run_command(wpr.cmd_import_csv, csv=str(self.csv_input("13")))
        self.assertEqual(self.data.read_bytes(), original.encode())


if __name__ == "__main__":
    unittest.main()
