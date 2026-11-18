"""Exercise offline Doc scope planning against synthetic native snapshots."""
import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from test_metrics_writes import CONFIG, wpr


def paragraph(text, heading=False, url=None):
    run = {"content": text + "\n"}
    if url:
        run["textStyle"] = {"link": {"url": url}}
    return {"paragraph": {"paragraphStyle": {"namedStyleType": "HEADING_1" if heading else "NORMAL_TEXT"},
                          "elements": [{"textRun": run}]}}


def snapshot(blocks, revision):
    blocks = copy.deepcopy(blocks)
    offset = 1
    for block in blocks:
        block["startIndex"] = offset
        text = block["paragraph"]["elements"][0]["textRun"]["content"]
        offset += len(text.encode("utf-16-le")) // 2
        block["endIndex"] = offset
    return {"revisionId": revision, "body": {"content": blocks}}


class DocRolloverTests(unittest.TestCase):
    def test_new_preview_close_and_rerun_older_week(self):
        newer, older = "2027-03-17", "2027-03-10"
        old_section = [paragraph("Week ending 10 March 2027", True),
                       paragraph("State: Closed"), paragraph("Source \U0001f4c4", url="https://example.test/old")]
        newer_link = paragraph("Source B", url="https://example.test/new")
        blocks = [paragraph("Synthetic review history", True), *old_section]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "wpr-config.md").write_text(CONFIG.replace("Friday", "Wednesday"), encoding="utf-8")
            (root / "reviews").mkdir()
            args = argparse.Namespace(wpr_dir=root, document=root / "snapshot.json", out=root / "plan.json", date=newer)

            def rerun(date, revision, replacement, expected_action):
                args.date = date
                heading = replacement[0]["paragraph"]["elements"][0]["textRun"]["content"].rstrip("\n")
                (root / "reviews" / f"{date}-wpr.md").write_text(f"# {heading}\n", encoding="utf-8")
                doc = snapshot(blocks, revision)
                args.document.write_text(json.dumps(doc), encoding="utf-8")
                wpr.cmd_plan_doc_sync(args)
                plan = json.loads(args.out.read_text(encoding="utf-8"))
                self.assertEqual(plan["heading"], heading)
                self.assertEqual(plan["action"], expected_action)
                self.assertEqual(plan["write_control"], {"requiredRevisionId": revision})
                starts = {block["startIndex"]: i for i, block in enumerate(doc["body"]["content"])}
                starts[doc["body"]["content"][-1]["endIndex"] - 1] = len(blocks)
                blocks[starts[plan["start_index"]]:starts[plan["end_index"]]] = replacement
                updated = snapshot(blocks, "after-write")
                for day in (newer, older):
                    self.assertEqual(wpr.plan_doc_sync(updated, dt.date.fromisoformat(day))["action"], "replace")
                headings = [b["paragraph"]["elements"][0]["textRun"]["content"].strip() for b in blocks
                            if b["paragraph"]["paragraphStyle"]["namedStyleType"] == "HEADING_1"]
                self.assertEqual(headings, ["Synthetic review history", "Week ending 17 March 2027", "Week ending 10 March 2027"])

            new_heading = paragraph("Week ending 17 March 2027", True)
            rerun(newer, "revision-1", [new_heading, paragraph("State: Preview"), newer_link], "insert")
            self.assertEqual(blocks[-3:], old_section)
            closed_section = [new_heading, paragraph("State: Closed"), newer_link]
            rerun(newer, "revision-2", closed_section, "replace")
            self.assertEqual(blocks[-3:], old_section)
            rerun(older, "revision-3", [old_section[0], paragraph("State: Closed, reviewed"), old_section[2]], "replace")
            self.assertEqual(blocks[1:4], closed_section)

    def test_duplicate_or_out_of_order_headings_fail_before_a_write(self):
        older = paragraph("Week ending 10 March 2027", True)
        newer = paragraph("Week ending 17 March 2027", True)
        for blocks in ([older, older], [older, newer]):
            with self.subTest(blocks=blocks), self.assertRaisesRegex(ValueError, "unique and newest first"):
                wpr.plan_doc_sync(snapshot(blocks, "revision"), dt.date(2027, 3, 17))

    def test_missing_older_week_goes_after_last_section(self):
        document = snapshot([paragraph("Week ending 17 March 2027", True), paragraph("A linked result", url="https://example.test/new")],
                            "revision")
        plan = wpr.plan_doc_sync(document, dt.date(2027, 3, 10))
        self.assertEqual(plan["action"], "insert")
        self.assertTrue(plan["at_end"])
        self.assertEqual(plan["start_index"], document["body"]["content"][-1]["endIndex"] - 1)
