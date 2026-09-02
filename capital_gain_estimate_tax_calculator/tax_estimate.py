"""User-supplied planning estimates for federal and state investment taxes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .guidance_mapping import BracketTaxComponent, GuidanceResponse, allocate_taxable_income, bracket_tax_components, standard_deduction_amount
from .models import NormalizedReport, ZERO, totals
from .settings import guidance_provider, tax_defaults, tax_input_defaults


US_STATES = (
    ("", "Select state"), ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"), ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"), ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"), ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"), ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"), ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"), ("MS", "Mississippi"), ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"), ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"), ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"), ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"), ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"), ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"), ("WV", "West Virginia"), ("WI", "Wisconsin"), ("WY", "Wyoming"), ("DC", "District of Columbia"),
)

FILING_STATUSES = (
    ("single", "Single"),
    ("married_filing_jointly", "Married filing jointly"),
    ("married_filing_separately", "Married filing separately"),
    ("head_of_household", "Head of household"),
    ("qualifying_surviving_spouse", "Qualifying surviving spouse"),
)


def state_name(state_code: str) -> str | None:
    """Return the full state name for a selected postal abbreviation."""
    return dict(US_STATES).get(state_code) if state_code else None


@dataclass(frozen=True)
class TaxAssumptions:
    """Household inputs used to request and apply bracket guidance."""

    state_code: str = ""
    filing_status: str = "single"
    num_dependents: int = 0
    ai_provider: str = "openai"
    other_ordinary_taxable_income: Decimal = ZERO


@dataclass(frozen=True)
class TaxEstimate:
    federal_short_term: Decimal = ZERO
    federal_long_term: Decimal = ZERO
    state: Decimal = ZERO

    @property
    def federal(self) -> Decimal:
        """Return the combined federal tax attributable to realized gains."""
        return self.federal_short_term + self.federal_long_term

    @property
    def total(self) -> Decimal:
        return self.federal + self.state


@dataclass(frozen=True)
class TaxFormulaLine:
    """The incremental-bracket calculation for one taxable gain class."""

    label: str
    opening_income: Decimal
    closing_income: Decimal
    components: tuple[BracketTaxComponent, ...]
    total_components: tuple[BracketTaxComponent, ...]

    @property
    def tax_amount(self) -> Decimal:
        return sum((component.taxable_amount * component.rate for component in self.components), ZERO)


@dataclass(frozen=True)
class TaxFormula:
    """All of the exact cumulative bracket calculations for one estimate."""

    federal_short_term: TaxFormulaLine
    federal_long_term: TaxFormulaLine
    state: TaxFormulaLine
    other_ordinary_income: Decimal
    short_term_gain: Decimal
    long_term_gain: Decimal
    standard_deduction: Decimal
    remaining_standard_deduction: Decimal

    @property
    def estimate(self) -> TaxEstimate:
        return TaxEstimate(
            federal_short_term=self.federal_short_term.tax_amount,
            federal_long_term=self.federal_long_term.tax_amount,
            state=self.state.tax_amount,
        )


def assumptions_from_form(values: dict[str, list[str]]) -> TaxAssumptions:
    """Read household inputs and preserved mapped rates from a submitted form."""
    default_status, default_dependents = tax_defaults()
    default_state, default_income = tax_input_defaults()
    status = values.get("filing_status", [default_status])[0]
    try:
        dependents = max(0, int(values.get("num_dependents", [str(default_dependents)])[0]))
    except (TypeError, ValueError):
        dependents = default_dependents
    provider = values.get("ai_provider", [guidance_provider()])[0].lower()
    return TaxAssumptions(
        state_code=values.get("state", [default_state])[0].upper(),
        filing_status=status if any(code == status for code, _ in FILING_STATUSES) else default_status,
        num_dependents=dependents,
        ai_provider=provider if provider in {"openai", "gemini", "openrouter"} else guidance_provider(),
        other_ordinary_taxable_income=_currency_amount(values.get("other_ordinary_taxable_income", [default_income])[0]),
    )


def estimate_taxes(
    report: NormalizedReport,
    assumptions: TaxAssumptions,
    guidance_response: GuidanceResponse | None = None,
) -> TaxEstimate:
    """Estimate tax on gains, using marginal brackets when approved guidance exists."""
    if guidance_response is None:
        return TaxEstimate()
    values = totals(report.lots)
    short_term = max(values["short_term_gain_loss_usd"], ZERO)
    long_term = max(values["long_term_gain_loss_usd"], ZERO)
    return build_tax_formula(guidance_response, assumptions.other_ordinary_taxable_income, short_term, long_term).estimate


def build_tax_formula(
    guidance_response: GuidanceResponse,
    ordinary_income: Decimal,
    short_term_gain: Decimal,
    long_term_gain: Decimal,
) -> TaxFormula:
    """Build the cumulative bracket calculations as each gain class stacks."""
    deduction = standard_deduction_amount(guidance_response)
    allocation = allocate_taxable_income(ordinary_income, short_term_gain, long_term_gain, deduction)
    return TaxFormula(
        federal_short_term=TaxFormulaLine(
            "Federal ordinary / short-term",
            allocation.federal_ordinary_opening,
            allocation.federal_ordinary_total,
            bracket_tax_components(guidance_response, "federal_ordinary", allocation.federal_ordinary_opening, allocation.federal_ordinary_total),
            bracket_tax_components(guidance_response, "federal_ordinary", ZERO, allocation.federal_ordinary_total),
        ),
        federal_long_term=TaxFormulaLine(
            "Federal long-term",
            ZERO,
            allocation.federal_long_term_total,
            bracket_tax_components(guidance_response, "federal_long_term", ZERO, allocation.federal_long_term_total),
            bracket_tax_components(guidance_response, "federal_long_term", ZERO, allocation.federal_long_term_total),
        ),
        state=TaxFormulaLine(
            "State",
            allocation.state_opening,
            allocation.state_total,
            bracket_tax_components(guidance_response, "state", allocation.state_opening, allocation.state_total),
            bracket_tax_components(guidance_response, "state", ZERO, allocation.state_total),
        ),
        other_ordinary_income=ordinary_income,
        short_term_gain=short_term_gain,
        long_term_gain=long_term_gain,
        standard_deduction=deduction,
        remaining_standard_deduction=allocation.remaining_standard_deduction,
    )
def _currency_amount(value: str) -> Decimal:
    try:
        return max(ZERO, Decimal(value.replace(",", "").replace("$", "").strip() or "0"))
    except (AttributeError, InvalidOperation):
        return ZERO
