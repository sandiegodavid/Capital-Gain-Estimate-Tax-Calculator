"""User-supplied planning estimates for federal and state investment taxes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from .models import ZERO, NormalizedReport, totals
from .settings import TaxProfileDefaults
from .state_dependent_benefits import StateDependentBenefitEstimate, estimate_state_dependent_benefits
from .tax_calculation import (
    BracketTaxComponent,
    allocate_taxable_income,
    bracket_tax_components,
)
from .tax_input_parser import TaxProfileInput, parse_tax_profile
from .tax_rules import TaxRuleBundle

US_STATES = (
    ("", "Select state"),
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
    ("DC", "District of Columbia"),
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
    """Household inputs used to apply local jurisdiction tax rules."""

    state_code: str = ""
    filing_status: str = "single"
    qualified_children: int = 0
    other_dependents: int = 0
    state_eligible_dependents: int | None = None
    other_ordinary_taxable_income: Decimal = ZERO
    short_term_carryover_loss: Decimal = ZERO
    long_term_carryover_loss: Decimal = ZERO


@dataclass(frozen=True)
class TaxCalculationRequest:
    """All inputs needed to build one auditable tax formula."""

    rules: TaxRuleBundle
    ordinary_income: Decimal
    short_term_gain: Decimal
    long_term_gain: Decimal
    short_carryover: Decimal = ZERO
    long_carryover: Decimal = ZERO
    filing_status: str = "single"
    assumptions: TaxAssumptions | None = None


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
class FederalDependentCreditEstimate:
    """Potential federal CTC/ODC after MAGI phaseout, before tax-liability limits."""

    amount: Decimal = ZERO
    phaseout_reduction: Decimal = ZERO


@dataclass(frozen=True)
class CarryoverApplication:
    """Net capital gains and the ordinary-income offset from prior-year losses."""

    short_term_gain: Decimal
    long_term_gain: Decimal
    ordinary_income_offset: Decimal


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
    state_short_term_gain: Decimal
    state_long_term_gain: Decimal
    federal_standard_deduction: Decimal
    state_standard_deduction: Decimal
    state_dependent_deduction: Decimal
    remaining_standard_deduction: Decimal
    state_calculation_supported: bool
    state_notice: str
    state_dependent_benefits: StateDependentBenefitEstimate

    @property
    def estimate(self) -> TaxEstimate:
        return TaxEstimate(
            federal_short_term=self.federal_short_term.tax_amount,
            federal_long_term=self.federal_long_term.tax_amount,
            state=self.state.tax_amount,
        )


def assumptions_from_form(
    values: dict[str, list[str]],
    saved_defaults: TaxProfileDefaults | None = None,
) -> TaxAssumptions:
    """Read household inputs and preserved mapped rates from a submitted form."""
    profile = saved_defaults or TaxProfileDefaults()
    selected_state = values.get("state", [profile.state_code])[0].upper()
    defaults = TaxProfileInput(
        profile.state_code,
        profile.filing_status,
        profile.qualified_children,
        profile.other_dependents,
        profile.state_eligible_dependents(selected_state),
        _currency_amount(profile.other_ordinary_taxable_income),
        _currency_amount(profile.short_term_carryover_loss),
        _currency_amount(profile.long_term_carryover_loss),
    )
    parsed = parse_tax_profile(values, defaults, frozenset(code for code, _ in FILING_STATUSES))
    return TaxAssumptions(
        state_code=parsed.state_code,
        filing_status=parsed.filing_status,
        qualified_children=parsed.qualified_children,
        other_dependents=parsed.other_dependents,
        state_eligible_dependents=parsed.state_eligible_dependents,
        other_ordinary_taxable_income=parsed.other_ordinary_taxable_income,
        short_term_carryover_loss=parsed.short_term_carryover_loss,
        long_term_carryover_loss=parsed.long_term_carryover_loss,
    )


def estimated_modified_adjusted_gross_income(
    other_ordinary_taxable_income: Decimal,
    short_term_gain: Decimal,
    long_term_gain: Decimal,
) -> Decimal:
    """Return the app's planning MAGI proxy from collected income and imported gains."""
    return max(other_ordinary_taxable_income + short_term_gain + long_term_gain, ZERO)


def estimate_federal_dependent_credits(
    rules: TaxRuleBundle,
    assumptions: TaxAssumptions,
    modified_adjusted_gross_income: Decimal,
) -> FederalDependentCreditEstimate:
    """Estimate nonrefundable CTC/ODC phaseout from confirmed eligibility and derived MAGI."""
    credit_rule = rules.federal_dependent_credit
    child_amount = credit_rule.child_credit_amount * assumptions.qualified_children
    other_amount = credit_rule.other_dependent_credit_amount * assumptions.other_dependents
    potential = child_amount + other_amount
    threshold_key = (
        "married_filing_jointly"
        if assumptions.filing_status == "married_filing_jointly"
        else "all_other_filing_statuses"
    )
    threshold = (
        credit_rule.joint_phaseout_threshold
        if threshold_key == "married_filing_jointly"
        else credit_rule.other_phaseout_threshold
    )
    reduction_per_increment = credit_rule.reduction_per_thousand
    excess = max(modified_adjusted_gross_income - threshold, ZERO)
    increments = (excess / Decimal("1000")).to_integral_value(rounding=ROUND_CEILING)
    reduction = min(potential, increments * reduction_per_increment)
    return FederalDependentCreditEstimate(potential - reduction, reduction)


def estimate_taxes(
    report: NormalizedReport,
    assumptions: TaxAssumptions,
    rules: TaxRuleBundle,
) -> TaxEstimate:
    """Estimate tax on gains from deterministic local jurisdiction rules."""
    values = totals(report.lots)
    short_term = values["short_term_gain_loss_usd"]
    long_term = values["long_term_gain_loss_usd"]
    return build_tax_formula(
        rules,
        assumptions.other_ordinary_taxable_income,
        short_term,
        long_term,
        assumptions.short_term_carryover_loss,
        assumptions.long_term_carryover_loss,
        assumptions.filing_status,
        assumptions,
    ).estimate


def build_tax_formula(
    rules: TaxRuleBundle,
    ordinary_income: Decimal,
    short_term_gain: Decimal,
    long_term_gain: Decimal,
    short_carryover: Decimal = ZERO,
    long_carryover: Decimal = ZERO,
    filing_status: str = "single",
    assumptions: TaxAssumptions | None = None,
) -> TaxFormula:
    """Compatibility entry point for callers that have not built a request yet."""
    return calculate_tax_formula(
        TaxCalculationRequest(
            rules,
            ordinary_income,
            short_term_gain,
            long_term_gain,
            short_carryover,
            long_carryover,
            filing_status,
            assumptions,
        )
    )


def calculate_tax_formula(request: TaxCalculationRequest) -> TaxFormula:
    """Build cumulative bracket calculations from one immutable calculation request."""
    rules = request.rules
    filing_status = request.filing_status
    ordinary_income = request.ordinary_income
    short_term_gain = request.short_term_gain
    long_term_gain = request.long_term_gain
    carryover = apply_carryover_losses(
        short_term_gain,
        long_term_gain,
        request.short_carryover,
        request.long_carryover,
        filing_status,
    )
    short_net = carryover.short_term_gain
    long_net = carryover.long_term_gain
    ordinary_income = max(ordinary_income - carryover.ordinary_income_offset, ZERO)
    calculation_rules = rules.calculation_rules
    federal_deduction = calculation_rules.federal_standard_deduction
    state_deduction = calculation_rules.state_standard_deduction
    benefit_assumptions = request.assumptions or TaxAssumptions(filing_status=filing_status)
    # State-specific dependent eligibility is not collected yet.  Until it is,
    # use the two explicitly confirmed federal dependent counts as a planning
    # proxy; the rendered estimate discloses that limitation.
    eligibility = {
        "state_eligible_dependents": benefit_assumptions.qualified_children + benefit_assumptions.other_dependents
    }
    state_benefits = estimate_state_dependent_benefits(
        rules,
        benefit_assumptions,
        {"state_agi": ordinary_income + short_net + long_net},
        eligibility,
    )
    allocation = allocate_taxable_income(ordinary_income, short_net, long_net, federal_deduction)
    state_short_net, state_long_net = rules.state_taxable_gains(short_net, long_net)
    state_allocation = allocate_taxable_income(
        ordinary_income, state_short_net, state_long_net, state_deduction + state_benefits.deduction
    )
    modeled_liability = sum(
        (
            component.taxable_amount * component.rate
            for component in bracket_tax_components(calculation_rules, "state", ZERO, state_allocation.state_total)
        ),
        ZERO,
    )
    state_benefits = estimate_state_dependent_benefits(
        rules,
        benefit_assumptions,
        {"state_agi": ordinary_income + short_net + long_net},
        eligibility,
        modeled_liability,
    )
    return TaxFormula(
        federal_short_term=TaxFormulaLine(
            "Federal ordinary / short-term",
            allocation.federal_ordinary_opening,
            allocation.federal_ordinary_total,
            bracket_tax_components(
                calculation_rules,
                "federal_ordinary",
                allocation.federal_ordinary_opening,
                allocation.federal_ordinary_total,
            ),
            bracket_tax_components(calculation_rules, "federal_ordinary", ZERO, allocation.federal_ordinary_total),
        ),
        federal_long_term=TaxFormulaLine(
            "Federal long-term",
            allocation.federal_long_term_opening,
            allocation.federal_long_term_total,
            bracket_tax_components(
                calculation_rules,
                "federal_long_term",
                allocation.federal_long_term_opening,
                allocation.federal_long_term_total,
            ),
            bracket_tax_components(calculation_rules, "federal_long_term", ZERO, allocation.federal_long_term_total),
        ),
        state=TaxFormulaLine(
            "State",
            state_allocation.state_opening,
            state_allocation.state_total,
            bracket_tax_components(
                calculation_rules, "state", state_allocation.state_opening, state_allocation.state_total
            ),
            bracket_tax_components(calculation_rules, "state", ZERO, state_allocation.state_total),
        ),
        other_ordinary_income=ordinary_income,
        short_term_gain=short_net,
        long_term_gain=long_net,
        state_short_term_gain=state_short_net,
        state_long_term_gain=state_long_net,
        federal_standard_deduction=federal_deduction,
        state_standard_deduction=state_deduction,
        state_dependent_deduction=state_benefits.deduction,
        remaining_standard_deduction=allocation.remaining_standard_deduction,
        state_calculation_supported=rules.state_calculation_supported,
        state_notice=rules.state_notice,
        state_dependent_benefits=state_benefits,
    )


def apply_carryover_losses(
    short_term_gain: Decimal,
    long_term_gain: Decimal,
    short_carryover: Decimal,
    long_carryover: Decimal,
    filing_status: str,
) -> CarryoverApplication:
    """Apply carryovers, cross-net capital results, then cap the ordinary-income offset."""
    short_net = short_term_gain - short_carryover
    long_net = long_term_gain - long_carryover
    if short_net > ZERO and long_net < ZERO:
        short_net = short_net + long_net
        long_net = ZERO
    elif long_net > ZERO and short_net < ZERO:
        long_net = long_net + short_net
        short_net = ZERO
    taxable_short = max(short_net, ZERO)
    taxable_long = max(long_net, ZERO)
    excess_loss = max(-(short_net + long_net), ZERO)
    annual_limit = Decimal("1500") if filing_status == "married_filing_separately" else Decimal("3000")
    return CarryoverApplication(taxable_short, taxable_long, min(excess_loss, annual_limit))


def _currency_amount(value: str) -> Decimal:
    try:
        return max(ZERO, Decimal(value.replace(",", "").replace("$", "").strip() or "0"))
    except (AttributeError, InvalidOperation):
        return ZERO
