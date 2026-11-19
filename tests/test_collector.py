import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from test_metrics_writes import wpr

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

    def partial_close(self):
        capture = json.loads((ROOT / "capture.partial-close.example.json").read_text(encoding="utf-8"))
        return collector.collect(capture, capture["captured_at"])

    def test_partial_close_matches_ledger_and_report_with_per_metric_coverage(self):
        records = {r["metric_id"]: r for r in self.partial_close()["records"]}
        cfg = wpr.load_config(ROOT / "wpr-config.md")
        week = next(w for w in wpr.load_metrics_data(ROOT / "metrics-data.md")
                    if w.week_date.isoformat() == "2027-02-05")
        closed = wpr.evaluate_metric_series(cfg, [week])
        expected = {"weekly_reach": ("verified", 250), "outcomes": ("verified-zero", 0),
                    "weekly_visitors": ("stale", None), "article_growth": ("unavailable", None)}
        for mid, (state, value) in expected.items():
            with self.subTest(metric=mid):
                self.assertEqual((records[mid]["state"], records[mid]["value"]), (state, value))
                self.assertEqual(closed[week.week_date, mid], value)
        self.assertEqual(records["weekly_visitors"]["observed"], 18)
        self.assertTrue(records["weekly_visitors"]["coverage_through"].startswith("2027-02-04"))
        self.assertEqual(records["article_growth"]["reason"], "Missing comparable baseline")
        with tempfile.TemporaryDirectory() as tmp:
            brief, rendered = wpr.generate_review_brief(cfg, [week], closed, Path(tmp))
        self.assertIn("Missing Sources", brief)
        self.assertIn("Missing comparable baseline", rendered)
        visitor = next(line for line in brief.splitlines() if "| Weekly Account Visitors |" in line)
        self.assertIn("| Stale source | 5 Feb 17:08 +01:00, through 4 Feb 17:00 |", visitor)

    def test_similar_dashboard_labels_and_repeat_reads_stay_separate(self):
        result = self.partial_close()
        impressions = [o for o in result["observations"] if o["source_label"] == "Impressions"]
        self.assertEqual([(o["window"], o["value"]) for o in impressions],
                         [("rolling-seven-days", 214), ("since-publication", 225), ("rolling-seven-days", 218)])
        self.assertEqual(len({o["captured_at"] for o in impressions}), 3)
        self.assertNotEqual(impressions[0]["period_start_exclusive"], impressions[1]["period_start_exclusive"])
        self.assertEqual({o["scope"] for o in result["observations"] if o["source_label"] == "Profile viewers"},
                         {"account", "post-a-attributed"})
        self.assertTrue(all(r["value"] not in {214, 218, 225} for r in result["records"]))

    def test_item_identity_aliases_and_snapshot_replay(self):
        capture = json.loads((ROOT / "capture.partial-close.example.json").read_text(encoding="utf-8"))
        result = collector.collect(capture, capture["captured_at"])
        items = {item["id"]: item for item in capture["items"]}
        self.assertEqual(items["post-a"]["promotes"], "tutorial-a")
        rows = result["item_snapshots"]
        self.assertEqual({row["window"] for row in rows if row["item_id"] == "post-a"},
                         {"rolling-seven-days", "since-publication"})
        self.assertEqual(collector.merge_snapshots(rows, rows), rows)
        self.assertEqual([row["item_alias"] for row in result["unresolved_item_observations"]], ["rank-7"])
        embedded, preceding = result["attribution_evidence"]
        self.assertIsNone(embedded["archive_url"])
        self.assertTrue(embedded["rendered_evidence"])
        self.assertIsNone(preceding["item_id"])

    def test_native_profile_and_utc_creator_windows_close_separately_from_local_events(self):
        capture = copy.deepcopy(self.capture)
        creator = {"period_start_exclusive": "2027-02-04T23:59:59.999999+00:00",
                   "period_end_inclusive": "2027-02-11T23:59:59.999999+00:00", "time_zone": "UTC"}
        profile = {"period_start_exclusive": "2027-02-03T23:59:59.999999-05:00",
                   "period_end_inclusive": "2027-02-10T23:59:59.999999-05:00", "time_zone": "America/New_York"}
        capture["source_windows"] = {"weekly_reach": creator, "weekly_visitors": profile}
        for metric, window in capture["source_windows"].items():
            capture["account"][metric].update(window, coverage_through=window["period_end_inclusive"])
        rows = self.records(capture)
        self.assertEqual([(rows[metric]["time_zone"], rows[metric]["value"])
                          for metric in ("weekly_reach", "weekly_visitors", "meetings")],
                         [("UTC", 640), ("America/New_York", 32), ("Europe/Berlin", 1)])
        shifted = capture["account"]["weekly_visitors"]
        shifted["period_end_inclusive"] = "2027-02-10T23:59:59.999999-04:00"
        self.assertIsNone(self.records(capture)["weekly_visitors"]["value"])

    def test_cutoff_minute_and_missing_channel_are_independent_at_close(self):
        capture = json.loads((ROOT / "capture.partial-close.example.json").read_text(encoding="utf-8"))
        capture["event_sources"] = {"attempts": {"available": False, "source": "Synthetic channel"}}
        records = self.records(capture, capture["captured_at"])
        self.assertEqual(records["weekly_reach"]["value"], 250)
        self.assertEqual(records["outcomes"]["state"], "verified-zero")
        self.assertEqual(records["attempts"]["state"], "unavailable")
        self.assertIsNone(records["attempts"]["value"])
        self.assertEqual(records["responses"]["value"], 1)
        self.assertIsNone(records["article_growth"]["value"])
        del capture["cutoff_minute"]
        self.assertEqual(self.records(capture, capture["captured_at"])["responses"]["reason"],
                         "Cutoff-minute event needs a reporting rule")

    def test_preview_brief_keeps_compact_coverage_and_expected_baseline_gap(self):
        cfg = wpr.load_config(ROOT / "wpr-config.md")
        closed = next(row for row in wpr.load_metrics_data(ROOT / "metrics-data.md") if row.period_state == "closed")
        closed.period_state = "preview"
        values = wpr.evaluate_metric_series(cfg, [closed])
        with tempfile.TemporaryDirectory() as tmp:
            markdown, rendered = wpr.generate_review_brief(cfg, [closed], values, Path(tmp))
        article = next(line for line in markdown.splitlines() if "Article Views Added" in line)
        self.assertIn("Missing comparable baseline", article)
        self.assertIn("closing counter at", article)
        self.assertIn("Missing comparable baseline", rendered)

    def test_booking_counts_once_at_confirmation_and_retains_later_attendance(self):
        capture = copy.deepcopy(self.capture)
        first, last = capture["period_start_exclusive"], capture["period_end_inclusive"]
        capture["events"] = [
            {"at": "2027-02-10T17:00:00+01:00", "kind": "meeting-confirmed", "meeting_id": "meeting-synthetic"},
        ]
        before = self.records(capture)["meetings"]["value"]
        next_cutoff = "2027-02-19T17:00:00+01:00"
        capture.update(period_start_exclusive=last, period_end_inclusive=next_cutoff,
                       captured_at=next_cutoff, coverage_through=next_cutoff)
        capture["events"].extend([
            {"at": "2027-02-15T11:00:00+01:00", "kind": "meeting-confirmed", "meeting_id": "meeting-synthetic"},
            {"at": "2027-02-17T10:00:00+01:00", "kind": "meeting-held", "meeting_id": "meeting-synthetic"},
        ])
        result = collector.collect(capture, next_cutoff)
        after = next(row["value"] for row in result["records"] if row["metric_id"] == "meetings")
        self.assertEqual((before, after), (1, 0))
        self.assertEqual([row["kind"] for row in result["event_evidence"]][-1], "meeting-held")
        # Reallocate from an incorrect held-week booking to its confirmed week.
        booked_before_restatement = {last: 0, next_cutoff: 1}
        capture.update(period_start_exclusive=first, period_end_inclusive=last)
        confirmed_week = self.records(capture, next_cutoff)["meetings"]["value"]
        restated = {last: confirmed_week, next_cutoff: after}
        self.assertEqual([restated[day] - prior for day, prior in booked_before_restatement.items()], [1, -1])
