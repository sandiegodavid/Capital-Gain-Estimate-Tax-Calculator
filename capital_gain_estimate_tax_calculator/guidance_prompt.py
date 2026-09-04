"""Prompt composition for planning-only tax-rate research."""

from __future__ import annotations

from .tax_estimate import TaxAssumptions


class TaxGuidancePromptBuilder:
    """Build a consistent, provider-neutral tax research prompt."""

    def build(self, year: int, residence: str, assumptions: TaxAssumptions) -> str:
        """Create the structured research prompt for one tax-year estimate."""
        return (
            f"For {year}, provide concise planning-only tax-rate research for a U.S. resident of "
            f"{residence} ({assumptions.state_code}). Explain federal short-term and long-term "
            f"capital-gain treatment and the state treatment for filing status {assumptions.filing_status} with "
            f"{assumptions.num_dependents} dependents and other ordinary taxable income of ${assumptions.other_ordinary_taxable_income:,.2f}. "
            "Use web search and cite only official IRS and state tax authority sources. "
            "Do not give personalized tax advice, calculate a taxpayer's liability, or recommend a payment amount. "
            "Reply with valid JSON only—no Markdown. Include the exact bracket-by-bracket rate breakdown in this structure: "
            '{"breakdowns":[{"type":"federal_ordinary","brackets":[{"bracket":50000,"rate":0},{"bracket":null,"rate":15}]},'
            '{"type":"federal_long_term","brackets":[{"bracket":50000,"rate":0},{"bracket":null,"rate":15}]},'
            '{"type":"state","brackets":[{"bracket":50000,"rate":0},{"bracket":null,"rate":15}]}],'
            f'"standard_deductions":{{"federal":{{"filing_status":"{assumptions.filing_status}","amount":15000}},"state":{{"filing_status":"{assumptions.filing_status}","amount":0}}}},'
            '"sources":[{"title":"IRS","url":"https://www.irs.gov"}]}. '
            "The type must be exactly federal_ordinary, federal_long_term, or state. "
            "Include federal and state standard_deductions for the selected filing status; each amount is the applicable U.S. dollar deduction. "
            "Use a breakdown for each applicable federal ordinary-income (short-term gain), federal long-term gain, and state treatment. "
            "In each bracket item, bracket is the upper taxable-income threshold in U.S. dollars and rate is the percentage."
        )
