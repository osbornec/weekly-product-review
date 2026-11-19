"""Synthetic connector readback distinguishes values, coverage, and preserved charts."""
import copy
import unittest

from test_metrics_writes import wpr


def simulate_batch(snapshot, operations):
    """Model atomic rejection of an unsupported optional chart operation."""
    if any(operation == "chart-position" for operation, _, _, _ in operations):
        raise ValueError("Connector rejects optional chart positioning")
    for operation, tab, cell, fields in operations:
        assert operation == "cell"
        snapshot[tab]["cells"][cell].update(fields)


def differences(expectations, snapshot):
    mismatches = {}
    for title, expected in expectations.items():
        actual = snapshot[title]
        issues = []
        for key, fields in expected["cells"].items():
            cell = actual["cells"].get(key, {})
            for field, value in fields.items():
                # A missing cell, numeric zero, and display text "0" are distinct.
                if field not in cell or type(cell[field]) is not type(value) or cell[field] != value:
                    issues.append((key, field))
        if "charts" in expected and actual["charts"] != expected["charts"]:
            issues.append(("charts", "metadata"))
        mismatches[title] = issues
    return mismatches


class BackfillReadbackTests(unittest.TestCase):
    def test_all_surfaces_and_smaller_retry(self):
        date = "2028-03-08"
        quarter = {"kind": "quarter", "year": 2028, "quarter": 1}
        annual = {"kind": "year", "year": 2028}
        layout = {"roles": {"coverage": 6, "closed_highlights": 10}, "metrics": {"bookings": 8, "visits": 9}}
        payload = {"row_signature": "layout", "catalog_signature": "catalog", "tabs": {
            name: {"week_columns": {date: column}, "values": [[""] * 4], "sheet_role": role, "row_layout": layout}
            for name, column, role in (("Quarter synthetic", "C", quarter), ("Annual synthetic", "D", annual))
        }}
        plan = wpr.plan_sync(payload, payload, date)
        # Resolve actual tabs and cells through readback-derived mappings which differ from the generated layout.
        live_layout = {
            "quarter": ("Weekly board", {date: "J"}, {"bookings": 12, "visits": 14, "coverage": 7, "closed_highlights": 20}),
            "year": ("Annual board", {date: "AB"}, {"bookings": 15, "visits": 18, "coverage": 9, "closed_highlights": 25}),
        }
        expected = {}
        for part in plan["tabs"]:
            title, dates, positions = live_layout[part["sheet_role"]["kind"]]
            col = dates[part["date"]]
            self.assertNotEqual(col, part["expected_column"])
            self.assertEqual(set(part["row_layout"]["metrics"]), {"bookings", "visits"})
            expected[title] = {"cells": {
                col + str(positions["bookings"]): {"value": 0, "note": "Captured 19:05Z"},
                col + str(positions["visits"]): {"value": None},
                col + str(positions["coverage"]): {"value": "Reviewed window", "link": "https://example.test/review"},
                col + str(positions["closed_highlights"]): {"value": "Verified booking count", "note": "Rechecked 19:05Z"},
                "current-preview": {"value": "0 so far", "link": "https://example.test/preview"},
            }}
        expected["Daily trend"] = {"cells": {"window": {"value": 35, "note": "UTC complete days"}},
                                   "charts": {71: {"source": "trend window", "position": "existing"}}}
        expected["Item archive"] = {"cells": {"dated-item": {"value": 8, "link": "https://example.test/item"}}}
        live = copy.deepcopy(expected)
        first = live["Weekly board"]["cells"]
        first["J12"]["note"] = "Old timestamp"
        first["J20"]["note"] = "Old coverage"
        del first["J7"]["link"]
        live["Daily trend"]["cells"]["window"]["value"] = 34
        del live["Item archive"]["cells"]["dated-item"]["link"]
        self.assertEqual(differences(expected, live), {
            "Weekly board": [("J12", "note"), ("J7", "link"), ("J20", "note")],
            "Annual board": [], "Daily trend": [("window", "value")], "Item archive": [("dated-item", "link")]})

        required = ("cell", "Daily trend", "window", {"value": 35})
        optional = ("chart-position", "Daily trend", 71, {"position": "elsewhere"})
        before = copy.deepcopy(live)
        with self.assertRaisesRegex(ValueError, "chart positioning"):
            simulate_batch(live, [required, optional])
        self.assertEqual(live["Daily trend"], before["Daily trend"])
        simulate_batch(live, [required])
        self.assertEqual(live["Daily trend"]["charts"], before["Daily trend"]["charts"])
        simulate_batch(live, [
            ("cell", "Weekly board", "J12", {"note": "Captured 19:05Z"}),
            ("cell", "Weekly board", "J7", {"link": "https://example.test/review"}),
            ("cell", "Weekly board", "J20", {"note": "Rechecked 19:05Z"}),
            ("cell", "Item archive", "dated-item", {"link": "https://example.test/item"}),
        ])
        self.assertEqual(differences(expected, live), {title: [] for title in expected})
        self.assertEqual(sum(type(cell["value"]) is int and cell["value"] == 0
                             for tab in live.values() for cell in tab["cells"].values()), 2)
        first["J12"]["value"] = "0"
        self.assertIn(("J12", "value"), differences(expected, live)["Weekly board"])
