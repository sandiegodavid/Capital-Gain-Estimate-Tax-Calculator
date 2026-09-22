"""Map local tax schedules and calculate marginal bracket components."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import ZERO, ReportError
from .tax_domain import BracketSchedule, TaxCalculationRules

BREAKDOWN_ALIASES = {
    "federal_ordinary": "federal_short_term",
    "federal_short_term": "federal_short_term",
    "short_term": "federal_short_term",
    "federal_long_term": "federal_long_term",
    "long_term": "federal_long_term",
    "state": "state",
    "state_income": "state",
}


@dataclass(frozen=True)
class MappedRate:
    rate: Decimal = ZERO
    bracket_upper_bound: Decimal | None = None


@dataclass(frozen=True)
class BracketTaxComponent:
    taxable_amount: Decimal
    rate: Decimal


@dataclass(frozen=True)
class TaxableIncomeAllocation:
    federal_ordinary_opening: Decimal
    federal_ordinary_total: Decimal
    federal_long_term_opening: Decimal
    federal_long_term_total: Decimal
    state_opening: Decimal
    state_total: Decimal
    remaining_standard_deduction: Decimal


@dataclass(frozen=True)
class TaxRateMapping:
    federal_short_term: MappedRate = MappedRate()
    federal_long_term: MappedRate = MappedRate()
    state: MappedRate = MappedRate()


def map_bracket_rates(rules: TaxCalculationRules, taxable_income: Decimal) -> TaxRateMapping:
    return TaxRateMapping(
        _select_bracket_rate(rules.federal_ordinary, taxable_income),
        _select_bracket_rate(rules.federal_long_term, taxable_income),
        _select_bracket_rate(rules.state_ordinary, taxable_income),
    )


def map_gain_rates(
    rules: TaxCalculationRules,
    ordinary_income: Decimal,
    short_term_gain: Decimal,
    long_term_gain: Decimal,
    standard_deduction: Decimal | None = None,
) -> TaxRateMapping:
    allocation = allocate_taxable_income(
        ordinary_income,
        short_term_gain,
        long_term_gain,
        rules.federal_standard_deduction if standard_deduction is None else standard_deduction,
    )
    return TaxRateMapping(
        federal_short_term=_rate_at_income(rules.federal_ordinary, allocation.federal_ordinary_total),
        federal_long_term=_rate_at_income(rules.federal_long_term, allocation.federal_long_term_total),
        state=_rate_at_income(rules.state_ordinary, allocation.state_total),
    )


def allocate_taxable_income(
    ordinary_income: Decimal,
    short_term_gain: Decimal,
    long_term_gain: Decimal,
    standard_deduction: Decimal,
) -> TaxableIncomeAllocation:
    ordinary_opening = max(ordinary_income - standard_deduction, ZERO)
    ordinary_total = max(ordinary_income + short_term_gain - standard_deduction, ZERO)
    remaining_deduction = max(standard_deduction - ordinary_income - short_term_gain, ZERO)
    taxable_long_term_gain = max(long_term_gain - remaining_deduction, ZERO)
    return TaxableIncomeAllocation(
        federal_ordinary_opening=ordinary_opening,
        federal_ordinary_total=ordinary_total,
        federal_long_term_opening=ordinary_total,
        federal_long_term_total=ordinary_total + taxable_long_term_gain,
        state_opening=max(ordinary_income - standard_deduction, ZERO),
        state_total=max(ordinary_income + short_term_gain + long_term_gain - standard_deduction, ZERO),
        remaining_standard_deduction=remaining_deduction,
    )


def bracket_tax_components(
    rules: TaxCalculationRules,
    breakdown_type: str,
    opening_income: Decimal,
    closing_income: Decimal,
) -> tuple[BracketTaxComponent, ...]:
    schedule = _schedule_for(rules, breakdown_type)
    if schedule is None:
        raise ReportError(f"Local tax rules do not include a {breakdown_type} rate schedule.")
    lower_bound = ZERO
    components: list[BracketTaxComponent] = []
    for band in schedule.bands:
        upper_bound, rate = band.upper_bound, band.rate
        lower = max(opening_income, lower_bound)
        upper = closing_income if upper_bound is None else min(closing_income, upper_bound)
        taxable_amount = max(ZERO, upper - lower)
        if taxable_amount > ZERO:
            components.append(BracketTaxComponent(taxable_amount, rate))
        if upper_bound is None or closing_income <= upper_bound:
            break
        lower_bound = upper_bound
    return tuple(reversed(components))


def _canonical_type(value: object) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return BREAKDOWN_ALIASES.get(normalized)


def _schedule_for(rules: TaxCalculationRules, breakdown_type: str) -> BracketSchedule | None:
    kind = _canonical_type(breakdown_type)
    if kind == "federal_short_term":
        return rules.federal_ordinary
    if kind == "federal_long_term":
        return rules.federal_long_term
    if kind == "state":
        return rules.state_ordinary
    return None


def _select_bracket_rate(schedule: BracketSchedule, taxable_income: Decimal) -> MappedRate:
    for band in schedule.bands:
        if band.upper_bound is None or taxable_income <= band.upper_bound:
            return MappedRate(band.rate, band.upper_bound)
    raise ReportError("A tax schedule did not include an open-ended bracket.")


def _rate_at_income(schedule: BracketSchedule, taxable_income: Decimal) -> MappedRate:
    return _select_bracket_rate(schedule, max(taxable_income, ZERO))
