import datetime as dt
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from test_metrics_writes import wpr


spec = importlib.util.spec_from_file_location(
    "workbook_exports", Path(__file__).resolve().parents[1] /
    "skills/weekly-product-review/examples/creator-wpr/workbook_exports.py")
exports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exports)

FIRST = dt.date(2028, 3, 5)
LAST = dt.date(2028, 3, 18)
TODAY = LAST + dt.timedelta(days=1)
NAME = "Creator export.xlsx"
REQUEST = "2028-03-19T14:00:00-04:00"
CHECK = "2028-03-19T14:05:00-04:00"


def make_export(path, last=LAST, changed=0, distinct=210, account="reed-lab", omit=None):
    days = exports.days_first_to_last(FIRST, last)
    daily = [[day.isoformat(), f"{1100 + (changed if day == LAST else 0):,}", "-2", "0"]
             for day in days if day != omit]
    metadata = [["account", account], ["first_utc_day", FIRST.isoformat()],
                ["last_utc_day", last.isoformat()],
                ["range_impressions", f"{sum(int(row[1].replace(',', '')) for row in daily):,}"],
                ["range_unique_members", str(distinct)]]

    def grid(rows):
        return [[{"v": value, "f": None, "fill": 0, "fmt": 0, "bold": False} for value in row] for row in rows]

    wpr.write_xlsx([("Export info", grid(metadata)),
                    ("Daily", grid([["utc_day", *exports.DAILY_METRICS], *daily])),
                    ("Optional demographics", grid([["Synthetic"]]))], path)
    stamp = exports.timestamp("2028-03-19T18:02:00Z").timestamp()
    os.utime(path, (stamp, stamp))
    return path


class WorkbookExportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name) / "custom downloads"
        self.directory.mkdir()

    def inspect(self, last=LAST, **options):
        return exports.inspect_download(self.directory, NAME, REQUEST, CHECK, "reed-lab",
                                        FIRST, last, wpr.read_xlsx_sheets, **options)

    def test_timeout_can_finish_with_fresh_suffixed_workbook(self):
        stale = make_export(self.directory / NAME)
        old_time = exports.timestamp("2028-03-19T17:55:00Z").timestamp()
        os.utime(stale, (old_time, old_time))
        self.assertEqual(self.inspect(waiting_for_save=True)["state"], "waiting-for-save")
        path = make_export(self.directory / "Creator export (2).xlsx")
        receipt = self.inspect(waiting_for_save=True, browser_event="timeout")
        self.assertEqual((receipt["state"], receipt["browser_event"], receipt["file"]),
                         ("saved", "timeout", path.name))
        self.assertEqual(receipt["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual((len(receipt["rows"]), receipt["range_unique_members"]), (14, 210))
        imported = exports.reconcile_daily({}, receipt)
        self.assertEqual((imported["state"], imported["added"]), ("imported", 14))
        with self.assertRaisesRegex(ValueError, "readback"):
            exports.verify_import(imported, {})
        self.assertEqual(exports.verify_import(imported, imported["ledger"])["state"], "verified")

    def test_incomplete_wrong_account_and_wrong_dates_leave_capture_pending(self):
        broken = self.directory / "Creator export (1).xlsx"
        broken.write_bytes(b"unfinished")
        stamp = exports.timestamp("2028-03-19T18:01:00Z").timestamp()
        os.utime(broken, (stamp, stamp))
        make_export(self.directory / "Creator export (2).xlsx", account="another-account")
        make_export(self.directory / "Creator export (3).xlsx", last=TODAY)
        make_export(self.directory / "Creator export (4).xlsx", omit=FIRST)
        result = self.inspect()
        self.assertEqual((result["state"], len(result["rejected"])), ("requested", 4))
        with self.assertRaisesRegex(ValueError, "saved workbook"):
            exports.reconcile_daily({}, result)

    def test_overlap_replay_revision_and_incomplete_week(self):
        path = self.directory / NAME
        make_export(path, last=TODAY)
        receipt = self.inspect(last=TODAY)
        first = exports.reconcile_daily({}, receipt)
        ledger = first["ledger"]
        self.assertEqual(first["added"], 14)
        self.assertEqual(first["open_days"], [TODAY.isoformat()])
        replay = exports.reconcile_daily(ledger, receipt)
        self.assertEqual((replay["added"], replay["ledger"]), (0, ledger))
        totals = exports.weekly_totals(ledger, TODAY)
        self.assertEqual(totals["values"], {"impressions": 7700, "export_engagements": -14, "new_followers": 0})
        self.assertEqual(len(totals["days"]), 7)

        make_export(path, changed=7)
        changed = self.inspect()
        staged = exports.reconcile_daily(ledger, changed, "Needs confirmation")
        self.assertEqual((staged["matched"], staged["held"], staged["restated"]), (13, 1, 0))
        held = staged["ledger"]
        self.assertEqual(held["days"][LAST.isoformat()]["impressions"], 1100)
        pending_week = exports.weekly_totals(held, TODAY)
        self.assertIsNone(pending_week["values"]["impressions"])
        self.assertEqual(pending_week["values"]["export_engagements"], -14)
        self.assertEqual(exports.reconcile_daily(held, changed, "Same file")["restated"], 0)
        make_export(path, changed=7, distinct=211)
        confirmed = exports.reconcile_daily(held, self.inspect(), "Independently re-exported")
        self.assertEqual((confirmed["restated"], confirmed["ledger"]["days"][LAST.isoformat()]["impressions"]),
                         (1, 1107))
        self.assertEqual(confirmed["ledger"]["restatements"][0]["previous"], 1100)
        del confirmed["ledger"]["days"][LAST.isoformat()]
        self.assertEqual(exports.weekly_totals(confirmed["ledger"], TODAY)["values"]["new_followers"], None)
