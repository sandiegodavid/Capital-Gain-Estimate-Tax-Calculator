"""Small use cases that coordinate domain operations through narrow ports."""

from __future__ import annotations

from dataclasses import dataclass

from .interfaces import TaxRuleRepository
from .models import NormalizedReport, totals
from .tax_estimate import TaxAssumptions, TaxCalculationRequest, TaxFormula, calculate_tax_formula
from .tax_rules import TaxRuleBundle


@dataclass(frozen=True)
class TaxCalculationResult:
    rules: TaxRuleBundle
    formula: TaxFormula


@dataclass(frozen=True)
class EstimateTaxes:
    rules: TaxRuleRepository

    def execute(self, report: NormalizedReport, assumptions: TaxAssumptions) -> TaxCalculationResult:
        """Build the auditable formula for one report and tax profile."""
        bundle = self.rules.load(
            report.report_year,
            assumptions.state_code,
            assumptions.filing_status,
            assumptions.qualified_children,
            assumptions.other_dependents,
        )
        values = totals(report.lots)
        formula = calculate_tax_formula(
            TaxCalculationRequest(
                bundle,
                assumptions.other_ordinary_taxable_income,
                values["short_term_gain_loss_usd"],
                values["long_term_gain_loss_usd"],
                assumptions.short_term_carryover_loss,
                assumptions.long_term_carryover_loss,
                assumptions.filing_status,
                assumptions,
            )
        )
        return TaxCalculationResult(bundle, formula)
