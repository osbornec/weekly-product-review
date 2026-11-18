"""Reviewed exports, safe links and action carry-over."""
import argparse
import contextlib
import io
import json
import unittest
from test_metrics_writes import wpr
import test_metrics_writes as fixtures


class ReviewTests(unittest.TestCase):
    setUp = fixtures.MetricsWritesTest.setUp

    def build(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(wpr.cmd_build(argparse.Namespace(wpr_dir=str(self.root), out_dir=str(self.root / "output"), active_tab_first=True, overwrite_review=False)), 0)

    def test_reviewed_content_is_selected_for_every_export(self):
        reviews = self.root / "reviews"
        reviews.mkdir()
        text = "# Reviewed report\n\n- **Reviewed Summary:** Investigate [evidence](https://example.test/evidence).\n\n| Item | Evidence |\n| --- | --- |\n| Decision | [Source](https://example.test/source) |\n"
        (reviews / "2027-01-08-wpr.md").write_text(text, encoding="utf-8")
        self.build()
        output = self.root / "output"
        self.assertEqual((output / "wpr-review-brief.md").read_text(), text)
        generated = (output / "wpr-review-draft.md").read_text()
        self.assertIn("Metric Highlights", generated)
        self.assertNotIn("# Reviewed report", generated)
        self.assertIn(text.strip(), (output / "wpr-review-archive.md").read_text())
        html = (output / "wpr-review-brief.html").read_text()
        self.assertIn('<a href="https://example.test/source">Source</a>', html)
        self.assertIn('<a href="https://example.test/evidence">evidence</a>', html)
        payload = json.loads((output / "sheets-payload.json").read_text())
        for name in ("Q1 27", "Full Year 2027"):
            tab = payload["tabs"][name]
            column = tab["week_columns"]["2027-01-08"]
            idx = wpr._col_ref_to_idx(column + "1")[1] - 1
            self.assertIn("https://example.test/evidence", tab["values"][-1][idx])

    def test_renderer_escapes_html_and_rejects_executable_links(self):
        html = wpr.render_brief_html("Safe", '- [bad](javascript:alert)\n- <script>bad()</script>\n- [good](https://example.test/?a=1&b=2)\n')
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('href="https://example.test/?a=1&amp;b=2"', html)

    def test_empty_summary_does_not_capture_next_heading(self):
        self.assertEqual(wpr.reviewed_summary("- **Reviewed Summary:** \n\n## 1. Metric Highlights\n"), "")

    def test_renderer_supports_relative_links_emphasis_and_escaped_table_pipe(self):
        html = wpr.render_brief_html("Safe", '| Name | Detail |\n| --- | --- |\n| **Value** | [History](../history.md) and a \\| marker |\n')
        self.assertIn('<a href="../history.md">History</a>', html)
        self.assertIn("<strong>Value</strong>", html)
        self.assertIn("and a | marker", html)

    def test_carry_over_uses_only_prior_decisions_and_retains_status(self):
        reviews = self.root / "reviews"
        reviews.mkdir()
        text = """## 1. Metrics
| Action | Owner | Due | Status |
| --- | --- | --- | --- |
| Unrelated Open metric | Team | Later | Open |

## 5. Decisions & Actions
### Instrumentation
| Action | Owner | Due | Status |
| --- | --- | --- | --- |
| Fix capture | Team | 2027-01-15 | In Progress |
| Completed action | Team | 2027-01-01 | Done |
"""
        (reviews / "2027-01-01-wpr.md").write_text(text)
        (reviews / "2027-01-15-wpr.md").write_text(text.replace("Fix capture", "Future action"))
        self.build()
        brief = (self.root / "output" / "wpr-review-brief.md").read_text()
        self.assertIn("| Fix capture | Team | 2027-01-15 | In Progress |", brief)
        self.assertNotIn("Unrelated Open metric", brief)
        self.assertNotIn("Future action", brief)
        self.assertNotIn("Completed action", brief)


if __name__ == "__main__":
    unittest.main()
