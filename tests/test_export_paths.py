"""Evidence links retain their meaning when reviews are exported elsewhere."""
import argparse
import contextlib
from html.parser import HTMLParser
import io
import json
import re
import unittest
from urllib.parse import unquote, urlsplit

import test_metrics_writes as fixtures
from test_metrics_writes import wpr


class ExportPathsTests(unittest.TestCase):
    setUp = fixtures.MetricsWritesTest.setUp

    def build(self):
        self.output = self.root / "exports/reports"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = wpr.cmd_build(argparse.Namespace(wpr_dir=str(self.root), out_dir=str(self.output),
                                                      active_tab_first=True, overwrite_review=False))
        self.assertEqual(result, 0)

    def test_relative_evidence_targets_survive_brief_html_archive_and_sheet_notes(self):
        evidence = self.root / "evidence/source notes.md"
        evidence.parent.mkdir()
        evidence.write_text("# Proof\n", encoding="utf-8")
        reviews = self.root / "reviews"
        reviews.mkdir()
        text = "# Reviewed report\n\n- **Reviewed Summary:** Check [evidence](../evidence/source%20notes.md?view=1#proof).\n"
        review = reviews / "2027-01-08-wpr.md"
        review.write_text(text, encoding="utf-8")
        self.build()
        target = "../../evidence/source%20notes.md?view=1#proof"
        for name in ("wpr-review-brief.md", "wpr-review-archive.md"):
            exported = (self.output / name).read_text(encoding="utf-8")
            self.assertIn("](" + target + ")", exported)
            url = urlsplit(re.search(r"\[evidence\]\(([^)]+)\)", exported)[1])
            self.assertEqual((self.output / unquote(url.path)).resolve(), evidence.resolve())
            self.assertEqual((url.query, url.fragment), ("view=1", "proof"))
            self.assertNotIn(str(self.root), exported)
        self.assertIn('href="' + target + '"', (self.output / "wpr-review-brief.html").read_text(encoding="utf-8"))
        payload = json.loads((self.output / "sheets-payload.json").read_text(encoding="utf-8"))
        self.assertIn(target, json.dumps(payload))
        self.assertEqual(review.read_text(encoding="utf-8"), text)

    def test_rebasing_preserves_web_fragment_and_code_links(self):
        text = "[web](https://example.test/proof?a=1#part) [section](#proof) ` [code](../not-a-link.md) `\n```md\n[code](../not-a-link.md)\n```\n"
        self.assertEqual(wpr.rebase_markdown_links(text, self.root / "reviews", self.root / "exports/reports"), text)

    def test_generated_draft_rebases_inherited_action_links_without_changing_review_source(self):
        reviews = self.root / "reviews"
        reviews.mkdir()
        (self.root / "evidence.md").write_text("Synthetic source", encoding="utf-8")
        (reviews / "2027-01-01-wpr.md").write_text("## Decisions\n| Action | Owner | Due | Status |\n| --- | --- | --- | --- |\n| Check [source](../evidence.md) | Team | Later | In Progress |\n", encoding="utf-8")
        self.build()
        self.assertIn("](../../evidence.md)", (self.output / "wpr-review-draft.md").read_text(encoding="utf-8"))
        self.assertIn("](../evidence.md)", (reviews / "2027-01-08-wpr.md").read_text(encoding="utf-8"))

    def test_html_loads_inter_from_google_fonts(self):
        class Resources(HTMLParser):
            def __init__(self):
                super().__init__()
                self.remote = []

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                address = values.get("src") if tag in {"script", "img", "iframe"} else values.get("href") if tag == "link" else None
                if address and address.startswith(("https://", "http://", "//")):
                    self.remote.append(address)

        parser = Resources()
        parser.feed(wpr.render_brief_html("Review", "[Optional evidence](https://example.test/proof)"))
        self.assertEqual(parser.remote, [
            "https://fonts.googleapis.com",
            "https://fonts.gstatic.com",
            "https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap",
        ])


if __name__ == "__main__":
    unittest.main()
