"""Failure injection into the real WPR workflow with local destination models."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from recovery_rehearsal import DEFAULT_SKILL, read, run


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wpr-recovery-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def check_destinations(self):
        for destination in ("sheet", "doc"):
            live = read(self.root / (destination + "-destination.json"))
            self.assertEqual(live["writes"], 1)
            self.assertEqual(live["periods"]["2027-02-05"], "prior-review-sentinel")
            self.assertEqual(len(live["periods"]), 2)
            self.assertEqual(live["custom"], {"chart": 73, "comment": "retain", "note": "retain"})

    def test_unavailable_and_stale_collection_preserve_existing_source_and_do_not_sync(self):
        for failure in ("collection-unavailable", "collection-stale"):
            with self.subTest(failure=failure):
                result = run(self.root, failure=failure)
                original = (DEFAULT_SKILL / "examples/creator-wpr/metrics-data.md").read_bytes()
                self.assertEqual((self.root / "wpr/metrics-data.md").read_bytes(), original)
                self.assertEqual(result["pending"], ["collection"])
                self.assertFalse((self.root / "output").exists())
                self.assertFalse((self.root / "sheet-destination.json").exists())
        self.assertTrue(run(self.root)["complete"])
        self.check_destinations()

    def test_partial_destination_failure_retries_only_pending_destination(self):
        for failure in ("sheet-unavailable", "doc-unavailable", "revision-conflict"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                self.root = Path(temp)
                first = run(self.root, failure=failure)
                failed = "sheet" if failure.startswith("sheet") else "doc"
                other = "doc" if failed == "sheet" else "sheet"
                self.assertFalse(first["complete"])
                self.assertEqual(first["pending"], [failed])
                before = (self.root / (other + "-destination.json")).read_bytes()
                self.assertTrue(run(self.root)["complete"])
                self.assertEqual((self.root / (other + "-destination.json")).read_bytes(), before)
                self.check_destinations()

    def test_failed_readback_is_pending_and_recovery_does_not_repeat_committed_write(self):
        for destination in ("sheet", "doc"):
            with self.subTest(destination=destination), tempfile.TemporaryDirectory() as temp:
                self.root = Path(temp)
                first = run(self.root, failure=destination + "-readback")
                self.assertEqual(first["pending"], [destination])
                if destination == "sheet":
                    self.assertFalse((self.root / "verified-sheet-payload.json").exists())
                self.assertTrue(run(self.root)["complete"])
                self.check_destinations()

    def test_process_restart_after_remote_commit_recovers_by_readback(self):
        script = Path(__file__).with_name("recovery_rehearsal.py")
        for destination in ("sheet", "doc"):
            with self.subTest(destination=destination), tempfile.TemporaryDirectory() as temp:
                self.root = Path(temp)
                args = [sys.executable, "-B", str(script), "--workspace", str(self.root)]
                result = subprocess.run(args + ["--failure", destination + "-crash-after-write"], capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 86, result.stderr)
                self.assertFalse(read(self.root / "run-state.json")["complete"])
                result = subprocess.run(args, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.check_destinations()

    def test_failed_recapture_after_success_preserves_verified_history(self):
        run(self.root)
        before = {p: p.read_bytes() for p in (self.root / "wpr").rglob("*") if p.is_file()}
        result = run(self.root, failure="collection-unavailable")
        self.assertFalse(result["complete"])
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertTrue(run(self.root)["complete"])
        self.check_destinations()

    def test_review_edit_for_same_date_refreshes_destinations_without_duplicate_periods(self):
        run(self.root)
        review = self.root / "wpr/reviews/2027-02-12-wpr.md"
        review.write_text(review.read_text(encoding="utf-8") + "\nReviewed update: synthetic evidence.\n", encoding="utf-8")
        self.assertTrue(run(self.root)["complete"])
        live = read(self.root / "doc-destination.json")
        self.assertEqual(live["writes"], 2)
        self.assertEqual(len(live["periods"]), 2)
        self.assertIn("Reviewed update", live["periods"]["2027-02-12"])

    def test_repeated_success_has_no_additional_destination_writes(self):
        first = run(self.root)
        self.assertTrue(first["complete"])
        for _ in range(2):
            self.assertTrue(run(self.root)["complete"])
        self.check_destinations()


if __name__ == "__main__":
    unittest.main()
