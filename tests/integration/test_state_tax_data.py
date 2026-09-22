from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from capital_gain_estimate_tax_calculator.tax_domain import DependentBenefitRule, TaxRuleSchemaError
from capital_gain_estimate_tax_calculator.tax_rules import TaxRuleStore

ROOT = Path(__file__).resolve().parents[2]
STATE_ROOT = ROOT / "tax_data" / "states"
STATUSES = {
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
    "qualifying_surviving_spouse",
}
BENEFIT_TYPES = {"deduction", "nonrefundable_credit", "refundable_credit"}
BENEFIT_BASES = {
    "state_eligible_dependent",
    "federal_confirmed_dependent",
    "child_under_age",
    "adopted_child",
    "college_dependent",
}
METHODS = {"fixed_per_dependent", "fixed_per_child"}


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class StateTaxDataTests(unittest.TestCase):
    def test_typed_benefit_translation_rejects_incomplete_calculable_rule(self):
        with self.assertRaises(TaxRuleSchemaError):
            DependentBenefitRule.from_mapping(
                {
                    "id": "broken",
                    "benefit_type": "deduction",
                    "eligibility_basis": "state_eligible_dependent",
                    "calculation": {"method": "fixed_per_dependent"},
                    "income_measure": "state_agi",
                    "filing_statuses": ["single"],
                    "calculation_supported": True,
                    "source_tax_year": 2026,
                    "status": "final",
                },
                2026,
            )

    @classmethod
    def setUpClass(cls):
        cls.manifest = load_yaml(STATE_ROOT / "2026-manifest.yaml")
        cls.expected = {row["abbreviation"] for row in cls.manifest["states"]}
        cls.paths = sorted(STATE_ROOT.glob("*/2026.yaml"))
        cls.data = {load_yaml(path)["abbreviation"]: load_yaml(path) for path in cls.paths}

    def test_coverage_matches_manifest(self):
        self.assertEqual(42, len(self.expected))
        self.assertEqual(set(self.expected), set(self.data))
        self.assertEqual(41, sum(d["tax_scope"] == "broad_individual_income_tax" for d in self.data.values()))
        self.assertEqual("capital_gains_excise_only", self.data["WA"]["tax_scope"])

    def test_manifest_matches_files_and_statuses(self):
        manifest = self.manifest
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

    def test_schema_sources_and_filing_urls(self):
        for abbreviation, data in self.data.items():
            with self.subTest(abbreviation=abbreviation):
                self.assertEqual("USD", data["currency"])
                self.assertEqual(
                    abbreviation.lower(),
                    next(p.parent.name for p in self.paths if p.parent.name == abbreviation.lower()),
                )
                self.assertIn(data["data_status"]["status"], {"final", "provisional"})
                if data["data_status"]["status"] == "final":
                    self.assertEqual([], data["data_status"]["unresolved_fields"])
                self.assertNotIn("payment", data["sources"])
                self.assertTrue(data["filing"]["payment_url"].startswith("https://"))
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

    def test_rule_store_translates_every_packaged_state_rule(self):
        store = TaxRuleStore()
        for abbreviation in self.data:
            with self.subTest(abbreviation=abbreviation):
                bundle = store.load(2026, abbreviation, "single")
                self.assertTrue(bundle.calculation_rules.federal_ordinary.bands)
                self.assertTrue(bundle.calculation_rules.federal_long_term.bands)
                self.assertIsNotNone(bundle.state_capital_gain_rule)

    def test_rule_store_rejects_an_unknown_filing_status(self):
        with self.assertRaisesRegex(TaxRuleSchemaError, "Unsupported filing status"):
            TaxRuleStore().load(2026, "CA", "not_a_filing_status")

    def test_dependent_benefits_have_explicit_safe_schema(self):
        count = supported = 0
        for abbreviation, data in self.data.items():
            for benefit in data.get("dependent_benefits", []):
                with self.subTest(abbreviation=abbreviation, benefit=benefit.get("id")):
                    count += 1
                    self.assertTrue(
                        {
                            "id",
                            "benefit_type",
                            "eligibility_basis",
                            "income_measure",
                            "calculation",
                            "phaseout",
                            "refundability",
                            "tax_liability_limit",
                            "source_tax_year",
                            "source",
                            "status",
                            "calculation_supported",
                        }
                        <= set(benefit)
                    )
                    self.assertIn(benefit["benefit_type"], BENEFIT_TYPES)
                    self.assertIn(benefit["eligibility_basis"], BENEFIT_BASES)
                    self.assertIn(
                        benefit["income_measure"],
                        {"federal_agi", "state_agi", "magi", "taxable_income", "not_applicable"},
                    )
                    self.assertIn(benefit["source"], data["sources"])
                    self.assertIsInstance(benefit["source_tax_year"], int)
                    self.assertIn(benefit["status"], {"final", "provisional"})
                    calculation = benefit["calculation"]
                    self.assertIn(calculation.get("method"), METHODS)
                    if benefit["calculation_supported"]:
                        supported += 1
                        self.assertTrue(benefit["phaseout"]["calculation_supported"])
                        self.assertIsInstance(calculation.get("amount"), (int, float))
                    else:
                        self.assertIn("unsupported_reason", benefit)
                        self.assertFalse(benefit["phaseout"]["calculation_supported"])
        self.assertEqual(37, count)
        self.assertEqual(13, supported)
        self.assertEqual(
            {"total": count, "calculation_supported": supported, "unsupported_or_informational": count - supported},
            self.manifest["coverage"]["dependent_benefits"],
        )

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
