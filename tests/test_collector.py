import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "skills" / "weekly-product-review" / "examples" / "creator-wpr"
SPEC = importlib.util.spec_from_file_location("synthetic_collector", ROOT / "collect_wpr.py")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.capture = json.loads((ROOT / "capture.example.json").read_text())

    def records(self, capture=None, as_of="2027-02-12T17:15:00+01:00"):
        return {r["metric_id"]: r for r in collector.collect(capture or self.capture, as_of)["records"]}

    def test_complete_capture_has_independent_scopes_and_verified_zero(self):
        records = self.records()
        self.assertEqual(records["weekly_reach"]["value"], 640)
        self.assertEqual(records["article_growth"]["value"], 27)
        self.assertEqual(records["attempts"]["value"], 3)
        self.assertEqual(records["meetings"]["value"], 1)
        self.assertEqual(records["outcomes"]["state"], "verified-zero")

    def test_open_period_never_emits_closed_values(self):
        capture = copy.deepcopy(self.capture)
        capture["captured_at"] = capture["coverage_through"] = "2027-02-10T12:00:00+01:00"
        for record in self.records(capture, as_of="2027-02-10T12:00:00+01:00").values():
            self.assertIsNone(record["value"])
            self.assertIn(record["state"], {"preview", "unavailable"})

    def test_failed_recapture_does_not_write_or_erase_history(self):
        original = (ROOT / "metrics-data.md").read_bytes()
        for mode in ("stale", "unavailable"):
            capture = copy.deepcopy(self.capture)
            if mode == "stale":
                capture["coverage_through"] = "2027-02-11T17:00:00+01:00"
            else:
                capture["available"] = False
            for record in self.records(capture).values():
                self.assertIsNone(record["value"])
                self.assertEqual(record["state"], mode)
        self.assertEqual((ROOT / "metrics-data.md").read_bytes(), original)

    def test_missing_or_revised_counter_is_unavailable(self):
        for prior in (None, 180):
            capture = copy.deepcopy(self.capture)
            capture["article_counter"]["prior"] = prior
            self.assertEqual(self.records(capture)["article_growth"]["state"], "unavailable")

    def test_timestamp_requires_offset(self):
        with self.assertRaises(ValueError):
            collector.stamp("2027-02-12T17:00:00")

    def test_future_capture_is_rejected(self):
        with self.assertRaises(ValueError):
            self.records(as_of="2027-02-01T12:00:00+01:00")

    def test_daylight_saving_offsets_keep_exclusive_and_inclusive_boundaries(self):
        capture = copy.deepcopy(self.capture)
        capture.update(period_start_exclusive="2027-03-26T17:00:00+01:00", period_end_inclusive="2027-04-02T17:00:00+02:00",
                       captured_at="2027-04-02T17:10:00+02:00", coverage_through="2027-04-02T17:00:00+02:00")
        capture["events"] = [{"at": capture["period_start_exclusive"], "kind": "attempt"},
                             {"at": capture["period_end_inclusive"], "kind": "attempt"}]
        self.assertEqual(self.records(capture, "2027-04-02T17:15:00+02:00")["attempts"]["value"], 1)
