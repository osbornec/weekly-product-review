"""Local-only checks of request shapes, types and preservation boundaries."""
import copy
import unittest

from connector_contracts import apply, requests
from test_metrics_writes import wpr


class ConnectorContractTests(unittest.TestCase):
    def setUp(self):
        tab = {"week_columns": {"2027-01-08": "H"},
               "values": [["=Literal label", 20, "", "", "", "", "", 0],
                          ["Units", "0012", "", "", "", "", "", ""],
                          ["  WoW Change", "", "", "", "", "", "", "=H1/I1"],
                          ["Notes", "", "", "", "", "", "", "Reviewed evidence"]]}
        self.payload = {"row_signature": "layout", "catalog_signature": "catalog", "tabs": {
            "Q1 27": copy.deepcopy(tab), "Full Year 2027": copy.deepcopy(tab),
            "Custom": {"week_columns": {}, "values": [["retain"]]}}}
        self.metadata = {title: {"sheet_id": index, "dates": {"2027-01-08": "H"}}
                         for index, title in enumerate(self.payload["tabs"], 101)}
        self.initial = {title: {(row, column): {"userEnteredValue": {"stringValue": "old"},
                                               "note": "retain note", "dataValidation": {"strict": True}}
                                for row in range(5) for column in range(10)} for title in self.metadata}

    def test_two_request_routes_preserve_types_blanks_prior_cells_notes_and_custom_tabs(self):
        plan = wpr.plan_sync(self.payload, None, "2027-01-08")
        destinations = []
        for route in ("drive", "workspace"):
            with self.subTest(route=route):
                calls = requests(plan, self.metadata, route)
                result = apply(self.initial, calls, route, self.metadata)
                destinations.append(result)
                for title in ("Q1 27", "Full Year 2027"):
                    self.assertEqual(result[title][0, 7]["userEnteredValue"], {"numberValue": 0})
                    self.assertNotIn("userEnteredValue", result[title][1, 7])
                    self.assertEqual(result[title][2, 7]["userEnteredValue"], {"formulaValue": "=H1/I1"})
                    self.assertEqual(result[title][0, 0]["userEnteredValue"], {"stringValue": "=Literal label"})
                    self.assertEqual(result[title][1, 1]["userEnteredValue"], {"stringValue": "0012"})
                    self.assertEqual(result[title][0, 7]["note"], "retain note")
                    self.assertEqual(result[title][1, 7]["dataValidation"], {"strict": True})
                    self.assertEqual(result[title][0, 8], self.initial[title][0, 8])
                self.assertEqual(result["Custom"], self.initial["Custom"])
        self.assertEqual(destinations[0], destinations[1])

    def test_live_column_drift_stops_before_constructing_formula_writes(self):
        plan = wpr.plan_sync(self.payload, self.payload, "2027-01-08")
        self.metadata["Q1 27"]["dates"]["2027-01-08"] = "I"
        for route in ("drive", "workspace"):
            with self.assertRaisesRegex(ValueError, "reconcile formula references"):
                requests(plan, self.metadata, route)

    def test_layout_change_stops_both_connector_routes_before_writes(self):
        previous = copy.deepcopy(self.payload)
        previous["row_signature"] = "old-layout"
        with self.assertRaisesRegex(ValueError, "row layout changed"):
            wpr.plan_sync(self.payload, previous, "2027-01-08")

    def test_repeat_plan_does_not_rewrite_catalog_or_custom_tab(self):
        plan = wpr.plan_sync(self.payload, self.payload, "2027-01-08")
        for route in ("drive", "workspace"):
            result = apply(self.initial, requests(plan, self.metadata, route), route, self.metadata)
            self.assertEqual(result["Q1 27"][0, 0], self.initial["Q1 27"][0, 0])
            self.assertEqual(result["Custom"], self.initial["Custom"])


if __name__ == "__main__":
    unittest.main()
