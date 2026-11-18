import copy
import unittest
from test_metrics_writes import wpr


class SyncPlanTests(unittest.TestCase):
    def payload(self):
        tab = {"week_columns": {"2027-01-08": "H"}, "values": [["Metric", "Target", "", "", "", "", "", "Date"], ["Units", "20", "", "", "", "", "", "12"]]}
        return {"row_signature": "stable-layout", "catalog_signature": "catalog-one", "tabs": {"Q1 27": copy.deepcopy(tab), "Full Year 2027": copy.deepcopy(tab), "Custom": {"week_columns": {}, "values": [["Retain this"]]}}}

    def test_plan_updates_actual_date_in_both_tabs_without_touching_custom(self):
        payload = self.payload()
        plan = wpr.plan_sync(payload, payload, "2027-01-08")
        self.assertEqual([tab["tab"] for tab in plan["tabs"]], ["Q1 27", "Full Year 2027"])
        self.assertEqual(plan["tabs"][0]["writes"], [{"range": "H1:H2", "values": [["Date"], ["12"]]}])
        self.assertEqual(wpr.plan_sync(payload, payload, "2027-01-08"), plan)

    def test_catalog_change_also_updates_labels_and_targets(self):
        payload = self.payload()
        previous = copy.deepcopy(payload)
        previous["catalog_signature"] = "old-catalog"
        plan = wpr.plan_sync(payload, previous, "2027-01-08")
        self.assertTrue(plan["catalog_changed"])
        self.assertEqual(plan["tabs"][0]["writes"][1]["range"], "A1:B2")

    def test_catalog_change_reaches_other_managed_quarters(self):
        payload = self.payload()
        payload["tabs"]["Q2 27"] = {"week_columns": {"2027-04-02": "H"}, "values": [["Other quarter", "25"]]}
        previous = copy.deepcopy(payload)
        previous["catalog_signature"] = "old"
        plan = wpr.plan_sync(payload, previous, "2027-01-08")
        quarter = next(tab for tab in plan["tabs"] if tab["tab"] == "Q2 27")
        self.assertIsNone(quarter["expected_column"])
        self.assertEqual(quarter["writes"][0]["range"], "A1:B1")

    def test_layout_change_requires_explicit_reconciliation(self):
        payload = self.payload()
        previous = copy.deepcopy(payload)
        previous["row_signature"] = "old-layout"
        with self.assertRaisesRegex(ValueError, "row layout changed"):
            wpr.plan_sync(payload, previous, "2027-01-08")


if __name__ == "__main__":
    unittest.main()
