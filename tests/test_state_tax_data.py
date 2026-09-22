from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "tax_data" / "states"
STATUSES = {
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
    "qualifying_surviving_spouse",
}


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class StateTaxDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payments = load_yaml(ROOT / "reference" / "income_tax_payment_websites.yaml")
        cls.expected = {
            entry["abbreviation"]: entry
            for entry in cls.payments
            if entry["abbreviation"] != "US"
        }
        cls.paths = sorted(STATE_ROOT.glob("*/2026.yaml"))
        cls.data = {load_yaml(path)["abbreviation"]: load_yaml(path) for path in cls.paths}

    def test_coverage_matches_reviewed_payment_reference(self):
        self.assertEqual(42, len(self.expected))
        self.assertEqual(set(self.expected), set(self.data))
        self.assertEqual(41, sum(d["tax_scope"] == "broad_individual_income_tax" for d in self.data.values()))
        self.assertEqual("capital_gains_excise_only", self.data["WA"]["tax_scope"])

    def test_manifest_matches_files_and_statuses(self):
        manifest = load_yaml(STATE_ROOT / "2026-manifest.yaml")
        rows = {row["abbreviation"]: row for row in manifest["states"]}
        self.assertEqual(set(self.data), set(rows))
        self.assertEqual(42, manifest["coverage"]["total_files"])
        counts = {status: 0 for status in ("final", "provisional")}
        for abbreviation, data in self.data.items():
            self.assertEqual(data["jurisdiction"], rows[abbreviation]["jurisdiction"])
            self.assertEqual(data["data_status"]["status"], rows[abbreviation]["status"])
            self.assertEqual(2026, data["tax_year"])
            counts[data["data_status"]["status"]] += 1
        self.assertEqual(manifest["status_counts"], counts)

    def test_schema_sources_and_payment_urls(self):
        for abbreviation, data in self.data.items():
            with self.subTest(abbreviation=abbreviation):
                self.assertEqual("USD", data["currency"])
                self.assertEqual(abbreviation.lower(), next(p.parent.name for p in self.paths if p.parent.name == abbreviation.lower()))
                self.assertIn(data["data_status"]["status"], {"final", "provisional"})
                if data["data_status"]["status"] == "final":
                    self.assertEqual([], data["data_status"]["unresolved_fields"])
                self.assertEqual(self.expected[abbreviation]["payment_url"], data["sources"]["payment"]["url"])
                for source in data["sources"].values():
                    self.assertTrue(source["url"].startswith("https://"), source)
                self.assertIn("capital_gains", data)
                self.assertIn("treatment", data["capital_gains"])
                self.assertEqual(STATUSES, set(data["standard_deduction"]) & STATUSES)

    def test_ordinary_schedules_are_ordered_and_open_ended(self):
        for abbreviation, data in self.data.items():
            if data["tax_scope"] != "broad_individual_income_tax":
                continue
            ordinary = data["brackets"]["ordinary"]
            self.assertEqual(STATUSES, set(ordinary), abbreviation)
            for status, rows in ordinary.items():
                with self.subTest(abbreviation=abbreviation, status=status):
                    self.assertIsNone(rows[-1]["bracket"])
                    finite = [row["bracket"] for row in rows[:-1]]
                    self.assertEqual(sorted(finite), finite)
                    self.assertTrue(all(isinstance(row["rate"], (int, float)) for row in rows))

    def test_representative_2026_values_and_capital_gain_rules(self):
        self.assertEqual(4.99, self.data["GA"]["brackets"]["ordinary"]["single"][0]["rate"])
        self.assertEqual(12875, self.data["LA"]["standard_deduction"]["single"])
        self.assertEqual(2, self.data["ME"]["brackets"]["surcharge"]["single"][-1]["rate"])
        self.assertEqual("full_subtraction", self.data["MO"]["capital_gains"]["treatment"])
        self.assertEqual(3, self.data["MT"]["brackets"]["long_term_capital_gains"]["single"][0]["rate"])
        self.assertEqual(2394.32, self.data["OH"]["tax_formula"]["nonbusiness_income"][-1]["base_tax"])
        self.assertEqual("5.21% of taxable income minus $966", self.data["SC"]["tax_formula"]["bands"][-1]["tax"])
        self.assertEqual(50750, self.data["VT"]["brackets"]["ordinary"]["single"][0]["bracket"])
        washington = self.data["WA"]
        self.assertIsNone(washington["standard_deduction"]["single"])
        self.assertEqual(278000, washington["standard_deduction"]["latest_published"]["amount"])
        self.assertEqual([7, 9.9], [row["rate"] for row in washington["brackets"]["long_term_capital_gains"]["single"]])


if __name__ == "__main__":
    unittest.main()
