"""Persist and map structured AI tax-rate guidance into usable rates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .models import ReportError, ZERO

GuidanceResponse = dict[str, object]

BREAKDOWN_TYPES = frozenset({"federal_ordinary", "federal_long_term", "state"})
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
    """One tax rate selected from a bracket schedule."""

    rate: Decimal = ZERO
    bracket_upper_bound: Decimal | None = None


@dataclass(frozen=True)
class BracketTaxComponent:
    """One portion of income taxed at one marginal rate."""

    taxable_amount: Decimal
    rate: Decimal


@dataclass(frozen=True)
class TaxableIncomeAllocation:
    """Taxable-income amounts after allocating the response's standard deduction."""

    federal_ordinary_opening: Decimal
    federal_ordinary_total: Decimal
    federal_long_term_total: Decimal
    state_opening: Decimal
    state_total: Decimal
    remaining_standard_deduction: Decimal


@dataclass(frozen=True)
class TaxRateMapping:
    """Rates applicable to the entered taxable income."""

    federal_short_term: MappedRate = MappedRate()
    federal_long_term: MappedRate = MappedRate()
    state: MappedRate = MappedRate()


def decode_guidance_response(guidance: str) -> GuidanceResponse:
    """Parse the JSON-only response required from a guidance provider."""
    cleaned = guidance.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        response = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ReportError("The AI response was not valid JSON, so its tax rates could not be applied.") from exc
    if not isinstance(response, dict):
        raise ReportError("The AI response must be a JSON object containing tax-rate breakdowns.")
    return response


def validate_guidance_response(response: GuidanceResponse, expected_filing_status: str | None = None) -> GuidanceResponse:
    """Validate and extract the rate breakdown, deduction, and source nodes."""
    breakdowns = response.get("breakdowns")
    if not isinstance(breakdowns, list):
        raise ReportError("The AI response did not include a breakdowns list.")

    validated_breakdowns: list[dict[str, object]] = []
    found_types: set[str] = set()
    for breakdown in breakdowns:
        if not isinstance(breakdown, dict):
            raise ReportError("Each breakdown must be a JSON object.")
        response_type = str(breakdown.get("type") or "").strip().lower()
        if response_type not in BREAKDOWN_TYPES:
            raise ReportError(f"Unsupported breakdown type: {response_type or 'missing'}.")
        if response_type in found_types:
            raise ReportError(f"Duplicate breakdown type: {response_type}.")
        validated_breakdowns.append({"type": response_type, "brackets": _validated_brackets(breakdown.get("brackets"))})
        found_types.add(response_type)

    missing = BREAKDOWN_TYPES - found_types
    if missing:
        raise ReportError(f"Missing breakdown types: {', '.join(sorted(missing))}.")

    deductions = response.get("standard_deductions")
    if not isinstance(deductions, dict):
        legacy = response.get("standard_deduction")
        if not isinstance(legacy, dict):
            raise ReportError("The AI response did not include federal and state standard deductions.")
        deductions = {"federal": legacy, "state": legacy}
    validated_deductions = {kind: _validated_deduction(deductions.get(kind), kind, expected_filing_status) for kind in ("federal", "state")}

    extracted: dict[str, object] = {
        "breakdowns": validated_breakdowns,
        "standard_deductions": validated_deductions,
    }
    sources = response.get("sources")
    if isinstance(sources, list):
        extracted["sources"] = sources
    return extracted


def map_bracket_rates(response: GuidanceResponse, taxable_income: Decimal) -> TaxRateMapping:
    """Select each applicable rate from the response's bracket breakdowns."""
    breakdowns = response.get("breakdowns")
    if not isinstance(breakdowns, list):
        raise ReportError("The AI response did not include a breakdowns list.")

    mapped: dict[str, MappedRate] = {}
    for breakdown in breakdowns:
        if not isinstance(breakdown, dict):
            continue
        kind = _canonical_type(breakdown.get("type"))
        if kind:
            mapped[kind] = _select_bracket_rate(breakdown.get("brackets"), taxable_income)

    missing = {"federal_short_term", "federal_long_term", "state"} - mapped.keys()
    if missing:
        labels = ", ".join(sorted(name.replace("_", " ") for name in missing))
        raise ReportError(f"The AI response did not include rate breakdowns for: {labels}.")
    return TaxRateMapping(
        federal_short_term=mapped["federal_short_term"],
        federal_long_term=mapped["federal_long_term"],
        state=mapped["state"],
    )


def map_gain_rates(
    response: GuidanceResponse,
    ordinary_income: Decimal,
    short_term_gain: Decimal,
    long_term_gain: Decimal,
) -> TaxRateMapping:
    """Map the highest marginal rate reached by each taxable-gain component."""
    allocation = allocate_taxable_income(
        ordinary_income,
        short_term_gain,
        long_term_gain,
        standard_deduction_amount(response),
    )
    schedules = _schedules_by_kind(response)
    return TaxRateMapping(
        federal_short_term=_rate_at_income(schedules["federal_short_term"], allocation.federal_ordinary_total),
        federal_long_term=_rate_at_income(schedules["federal_long_term"], allocation.federal_long_term_total),
        state=_rate_at_income(schedules["state"], allocation.state_total),
    )


def allocate_taxable_income(
    ordinary_income: Decimal,
    short_term_gain: Decimal,
    long_term_gain: Decimal,
    standard_deduction: Decimal,
) -> TaxableIncomeAllocation:
    """Allocate a standard deduction across ordinary/short-term income first."""
    ordinary_opening = max(ordinary_income - standard_deduction, ZERO)
    ordinary_total = max(ordinary_income + short_term_gain - standard_deduction, ZERO)
    remaining_deduction = max(standard_deduction - ordinary_income - short_term_gain, ZERO)
    return TaxableIncomeAllocation(
        federal_ordinary_opening=ordinary_opening,
        federal_ordinary_total=ordinary_total,
        federal_long_term_total=max(long_term_gain - remaining_deduction, ZERO),
        state_opening=ordinary_income - standard_deduction,
        state_total=ordinary_income + short_term_gain + long_term_gain - standard_deduction,
        remaining_standard_deduction=remaining_deduction,
    )


def standard_deduction_amount(response: GuidanceResponse, jurisdiction: str = "federal") -> Decimal:
    """Return the validated standard deduction supplied by the selected response."""
    deductions = response.get("standard_deductions")
    deduction = deductions.get(jurisdiction) if isinstance(deductions, dict) else response.get("standard_deduction")
    amount = deduction.get("amount") if isinstance(deduction, dict) else None
    parsed = _decimal(amount)
    if parsed is None or parsed < ZERO:
        raise ReportError("The AI response did not include a valid standard deduction amount.")
    return parsed


def _validated_deduction(value: object, jurisdiction: str, expected_filing_status: str | None) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReportError(f"The AI response did not include a {jurisdiction} standard deduction.")
    filing_status = value.get("filing_status")
    amount = _decimal(value.get("amount"))
    if not isinstance(filing_status, str) or not filing_status.strip() or amount is None or amount < ZERO:
        raise ReportError(f"The {jurisdiction} standard deduction must include a filing_status and non-negative amount.")
    normalized_status = filing_status.strip().lower().replace(" ", "_")
    if expected_filing_status and normalized_status != expected_filing_status:
        raise ReportError(f"The {jurisdiction} standard deduction is for {normalized_status}, not the requested {expected_filing_status} filing status.")
    return {"filing_status": normalized_status, "amount": float(amount)}


def bracket_tax_components(
    response: GuidanceResponse,
    breakdown_type: str,
    opening_income: Decimal,
    closing_income: Decimal,
) -> tuple[BracketTaxComponent, ...]:
    """Return the taxable portions of an income increase, highest bracket first."""
    schedule = _schedules_by_kind(response).get(_canonical_type(breakdown_type) or "")
    if schedule is None:
        raise ReportError(f"The AI response did not include a {breakdown_type} rate breakdown.")
    lower_bound = ZERO
    components: list[BracketTaxComponent] = []
    for upper_bound, rate in _normalized_brackets(schedule):
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


def _schedules_by_kind(response: GuidanceResponse) -> dict[str, object]:
    breakdowns = response.get("breakdowns")
    if not isinstance(breakdowns, list):
        raise ReportError("The AI response did not include a breakdowns list.")
    schedules = {
        kind: breakdown.get("brackets")
        for breakdown in breakdowns
        if isinstance(breakdown, dict) and (kind := _canonical_type(breakdown.get("type")))
    }
    missing = {"federal_short_term", "federal_long_term", "state"} - schedules.keys()
    if missing:
        labels = ", ".join(sorted(name.replace("_", " ") for name in missing))
        raise ReportError(f"The AI response did not include rate breakdowns for: {labels}.")
    return schedules


def _select_bracket_rate(value: object, taxable_income: Decimal) -> MappedRate:
    if not isinstance(value, list) or not value:
        raise ReportError("Each AI tax-rate breakdown must include at least one bracket.")
    brackets: list[tuple[Decimal | None, Decimal]] = []
    for bracket in value:
        if not isinstance(bracket, dict):
            continue
        rate = _decimal(bracket.get("rate"))
        if rate is None:
            continue
        brackets.append((_decimal(bracket.get("bracket")), rate / Decimal("100")))
    if not brackets:
        raise ReportError("The AI response contained no usable bracket rates.")
    ordered = sorted(brackets, key=lambda item: (item[0] is None, item[0] or ZERO))
    for upper_bound, rate in ordered:
        if upper_bound is None or taxable_income <= upper_bound:
            return MappedRate(rate, upper_bound)
    upper_bound, rate = ordered[-1]
    return MappedRate(rate, upper_bound)


def _rate_at_income(value: object, taxable_income: Decimal) -> MappedRate:
    """Return the highest bracket reached by a non-negative income amount."""
    return _select_bracket_rate(value, max(taxable_income, ZERO))


def _normalized_brackets(value: object) -> list[tuple[Decimal | None, Decimal]]:
    if not isinstance(value, list) or not value:
        raise ReportError("Each AI tax-rate breakdown must include at least one bracket.")
    brackets: list[tuple[Decimal | None, Decimal]] = []
    for bracket in value:
        if not isinstance(bracket, dict):
            continue
        rate = _decimal(bracket.get("rate"))
        if rate is not None:
            brackets.append((_decimal(bracket.get("bracket")), rate / Decimal("100")))
    if not brackets:
        raise ReportError("The AI response contained no usable bracket rates.")
    return sorted(brackets, key=lambda item: (item[0] is None, item[0] or ZERO))


def _validated_brackets(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ReportError("Each breakdown must include at least one bracket.")
    validated: list[dict[str, object]] = []
    for bracket in value:
        if not isinstance(bracket, dict):
            raise ReportError("Each rate bracket must be a JSON object.")
        threshold = bracket.get("bracket")
        amount = _decimal(threshold) if threshold is not None else None
        rate = _decimal(bracket.get("rate"))
        if (threshold is not None and (amount is None or amount < ZERO)) or rate is None or not ZERO <= rate <= Decimal("100"):
            raise ReportError("Each bracket must contain a non-negative threshold (or null) and a rate from 0 to 100.")
        validated.append({"bracket": float(amount) if amount is not None else None, "rate": float(rate)})
    return validated


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
