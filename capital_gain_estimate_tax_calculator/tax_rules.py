"""Load deterministic, year-versioned federal and state tax rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from .models import ZERO, ReportError
from .tax_domain import (
    BracketBand,
    BracketSchedule,
    CapitalGainRule,
    CapitalGainTreatment,
    DependentBenefitRule,
    FederalDependentCreditRule,
    FilingStatus,
    JurisdictionRuleDisplay,
    TaxCalculationRules,
    TaxRuleBracketTable,
    TaxRuleCard,
    TaxRuleDetail,
    TaxRuleDisplay,
    TaxRuleSchemaError,
)

TAX_DATA_ROOT = Path(__file__).resolve().parent.parent / "tax_data"
NO_BROAD_INCOME_TAX_STATES = frozenset({"AK", "FL", "NV", "NH", "SD", "TN", "TX", "WY"})
SUPPORTED_STATE_TREATMENTS = frozenset(
    {
        "ordinary_schedule",
        "percentage_exclusion_then_ordinary_schedule",
        "full_subtraction",
        "deduction_then_ordinary_schedule",
    }
)


def _load_yaml(path: Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportError(f"No local tax rules are available for {path.stem}.") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise ReportError(f"Could not load local tax rules from {path}.") from exc
    if not isinstance(value, dict):
        raise ReportError(f"Local tax rules in {path} are not a YAML object.")
    return value


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ReportError(f"Invalid numeric value in local tax rules: {value!r}.") from exc


@dataclass(frozen=True)
class TaxRuleBundle:
    """Federal rules plus the selected state rules for one tax profile."""

    year: int
    filing_status: FilingStatus
    state_code: str
    state_name: str
    state_calculation_supported: bool
    calculation_rules: TaxCalculationRules
    state_capital_gain_rule: CapitalGainRule
    display: TaxRuleDisplay
    state_notice: str = ""
    dependent_benefit_rules: tuple[DependentBenefitRule, ...] = ()
    federal_dependent_credit: FederalDependentCreditRule = FederalDependentCreditRule()

    def standard_deduction(self, jurisdiction: str) -> Decimal:
        if jurisdiction == "federal":
            return self.calculation_rules.federal_standard_deduction
        return self.calculation_rules.state_standard_deduction

    def state_taxable_gains(self, short_gain: Decimal, long_gain: Decimal) -> tuple[Decimal, Decimal]:
        """Apply explicit state capital-gain exclusions supported by the local schema."""
        if not self.state_calculation_supported:
            return ZERO, ZERO
        rule = self.state_capital_gain_rule
        if rule.treatment is CapitalGainTreatment.FULL_SUBTRACTION:
            return ZERO, ZERO
        if rule.treatment is CapitalGainTreatment.PERCENTAGE_EXCLUSION_THEN_ORDINARY_SCHEDULE:
            return short_gain, max(long_gain * (Decimal("1") - rule.exclusion_percent), ZERO)
        if rule.treatment is CapitalGainTreatment.DEDUCTION_THEN_ORDINARY_SCHEDULE:
            excluded = max(rule.fixed_deduction, long_gain * rule.deduction_percent)
            return short_gain, max(long_gain - excluded, ZERO)
        return short_gain, long_gain


class TaxRuleStore:
    """Read local jurisdiction rules and decide whether exact calculation is supported."""

    def __init__(self, root: Path = TAX_DATA_ROOT) -> None:
        self.root = root

    def load(
        self,
        year: int,
        state_code: str,
        filing_status: str,
        qualified_children: int = 0,
        other_dependents: int = 0,
    ) -> TaxRuleBundle:
        try:
            status = FilingStatus(filing_status)
        except ValueError as exc:
            raise TaxRuleSchemaError(f"Unsupported filing status: {filing_status!r}.") from exc
        federal = _load_yaml(self.root / "federal" / f"{year}.yaml")
        federal_dependent_credit = _federal_dependent_credit(federal)
        federal_calculation_rules = _calculation_rules(federal, None, status, False)
        no_state_capital_gain_rule = CapitalGainRule(CapitalGainTreatment.ORDINARY_SCHEDULE, True)
        no_state_display = _rule_display(federal, None, status)
        code = state_code.strip().upper()
        if not code:
            return TaxRuleBundle(
                year=year,
                filing_status=status,
                state_code=code,
                state_name=code,
                state_calculation_supported=False,
                calculation_rules=federal_calculation_rules,
                state_capital_gain_rule=no_state_capital_gain_rule,
                display=no_state_display,
                state_notice="Select a state residence to calculate state tax.",
                federal_dependent_credit=federal_dependent_credit,
            )
        path = self.root / "states" / code.lower() / f"{year}.yaml"
        if not path.is_file():
            if code in NO_BROAD_INCOME_TAX_STATES:
                return TaxRuleBundle(
                    year=year,
                    filing_status=status,
                    state_code=code,
                    state_name=code,
                    state_calculation_supported=True,
                    calculation_rules=federal_calculation_rules,
                    state_capital_gain_rule=no_state_capital_gain_rule,
                    display=no_state_display,
                    state_notice="This state has no broad individual income tax in the local rules.",
                    federal_dependent_credit=federal_dependent_credit,
                )
            return TaxRuleBundle(
                year=year,
                filing_status=status,
                state_code=code,
                state_name=code,
                state_calculation_supported=False,
                calculation_rules=federal_calculation_rules,
                state_capital_gain_rule=no_state_capital_gain_rule,
                display=no_state_display,
                state_notice=f"No local {year} tax-rule file is available for {code}.",
                federal_dependent_credit=federal_dependent_credit,
            )

        state = _load_yaml(path)
        state_capital_gain_rule = _capital_gain_rule(state)
        raw_benefits = state.get("dependent_benefits", [])
        if not isinstance(raw_benefits, list):
            raise TaxRuleSchemaError(f"State dependent_benefits in {path} must be a list.")
        try:
            dependent_benefits = tuple(
                DependentBenefitRule.from_mapping(item, year) for item in raw_benefits if isinstance(item, dict)
            )
        except TaxRuleSchemaError as exc:
            raise ReportError(f"Invalid state dependent-benefit rule in {path}: {exc}") from exc
        standard = state.get("standard_deduction")
        capital = state.get("capital_gains")
        treatment = capital.get("treatment") if isinstance(capital, dict) else None
        standard_supported = not isinstance(standard, dict) or standard.get("calculation_supported") is not False
        capital_supported = isinstance(capital, dict) and capital.get("calculation_supported") is True
        generic_formula = "tax_formula" not in state
        treatment_supported = treatment in SUPPORTED_STATE_TREATMENTS
        supported = standard_supported and capital_supported and generic_formula and treatment_supported
        note = ""
        if not supported:
            note = "The local rule file contains the official data, but marks one or more required state calculations as unsupported; no state estimate is shown."
        return TaxRuleBundle(
            year=year,
            filing_status=status,
            state_code=code,
            state_name=str(state.get("jurisdiction", code)),
            state_calculation_supported=supported,
            calculation_rules=_calculation_rules(federal, state, status, supported),
            state_capital_gain_rule=state_capital_gain_rule,
            display=_rule_display(federal, state, status),
            state_notice=note,
            dependent_benefit_rules=dependent_benefits,
            federal_dependent_credit=federal_dependent_credit,
        )


def _calculation_rules(
    federal: dict[str, object],
    state: dict[str, object] | None,
    filing_status: FilingStatus,
    state_calculation_supported: bool,
) -> TaxCalculationRules:
    federal_brackets = federal.get("brackets")
    ordinary = federal_brackets.get("ordinary") if isinstance(federal_brackets, dict) else None
    long_term = federal_brackets.get("long_term") if isinstance(federal_brackets, dict) else None
    federal_deductions = federal.get("standard_deduction")
    if not isinstance(ordinary, dict) or not isinstance(long_term, dict) or not isinstance(federal_deductions, dict):
        raise TaxRuleSchemaError("Federal tax calculation rules are incomplete.")
    federal_ordinary = _bracket_schedule(ordinary.get(filing_status.value), "federal ordinary")
    federal_long_term = _bracket_schedule(long_term.get(filing_status.value), "federal long-term")
    federal_deduction = _deduction_amount(federal_deductions.get(filing_status.value), "federal")

    state_schedule = BracketSchedule((BracketBand(None, ZERO),))
    state_deduction = ZERO
    if state_calculation_supported and state:
        state_brackets = state.get("brackets")
        state_ordinary = state_brackets.get("ordinary") if isinstance(state_brackets, dict) else None
        state_deductions = state.get("standard_deduction")
        if not isinstance(state_ordinary, dict) or not isinstance(state_deductions, dict):
            raise TaxRuleSchemaError("State tax calculation rules are incomplete.")
        state_schedule = _bracket_schedule(state_ordinary.get(filing_status.value), "state ordinary")
        state_deduction = _deduction_amount(state_deductions.get(filing_status.value), "state")
    return TaxCalculationRules(
        federal_ordinary,
        federal_long_term,
        state_schedule,
        federal_deduction,
        state_deduction,
    )


def _rule_display(
    federal: dict[str, object], state: dict[str, object] | None, filing_status: FilingStatus
) -> TaxRuleDisplay:
    return TaxRuleDisplay(
        _jurisdiction_display(federal, filing_status, ("credits",)),
        _jurisdiction_display(state, filing_status, ("dependent_benefits", "other_credits")),
    )


def _jurisdiction_display(
    rules: dict[str, object] | None,
    filing_status: FilingStatus,
    credit_keys: tuple[str, ...],
) -> JurisdictionRuleDisplay:
    if rules is None:
        return JurisdictionRuleDisplay((), None, (), ())
    brackets = rules.get("brackets")
    tables: list[TaxRuleBracketTable] = []
    if isinstance(brackets, dict):
        for name, schedules in brackets.items():
            selected = schedules.get(filing_status.value) if isinstance(schedules, dict) else None
            if isinstance(selected, list):
                try:
                    tables.append(TaxRuleBracketTable(_display_label(name), _bracket_schedule(selected, str(name))))
                except TaxRuleSchemaError:
                    continue
    deduction = rules.get("standard_deduction")
    selected_deduction = deduction.get(filing_status.value) if isinstance(deduction, dict) else None
    standard_details = (
        tuple(
            TaxRuleDetail(_display_label(key), _display_value(value))
            for key, value in deduction.items()
            if key
            not in {
                "single",
                "married_filing_jointly",
                "married_filing_separately",
                "head_of_household",
                "qualifying_surviving_spouse",
                "calculation_supported",
            }
        )
        if isinstance(deduction, dict)
        else ()
    )
    cards: list[TaxRuleCard] = []
    for key in credit_keys:
        values = rules.get(key)
        if key == "credits":
            if not isinstance(values, dict):
                continue
            entries: list[tuple[object, object]] = list(values.items())
        else:
            if not isinstance(values, list):
                continue
            entries = list(enumerate(values))
        for name, entry in entries:
            if not isinstance(entry, dict):
                continue
            title = name if key == "credits" else entry.get("name", entry.get("id", "Credit"))
            cards.append(
                TaxRuleCard(
                    _display_label(title),
                    tuple(
                        TaxRuleDetail(_display_label(detail), _display_value(value))
                        for detail, value in entry.items()
                        if detail != "name"
                    ),
                )
            )
    parsed_deduction = _decimal(selected_deduction) if isinstance(selected_deduction, (int, float)) else None
    return JurisdictionRuleDisplay(tuple(tables), parsed_deduction, standard_details, tuple(cards))


def _display_label(value: object) -> str:
    return str(value).replace("_", " ").strip().capitalize()


def _display_value(value: object) -> str:
    if value is None:
        return "Not specified"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, dict):
        return "; ".join(f"{_display_label(key)}: {_display_value(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(_display_value(item) for item in value)
    return str(value)


def _capital_gain_rule(state: dict[str, object]) -> CapitalGainRule:
    capital = state.get("capital_gains")
    if not isinstance(capital, dict):
        raise TaxRuleSchemaError("State capital-gain rules are incomplete.")
    try:
        treatment = CapitalGainTreatment(str(capital.get("treatment")))
    except ValueError as exc:
        raise TaxRuleSchemaError("State capital-gain treatment is invalid.") from exc
    calculation_supported = capital.get("calculation_supported")
    if not isinstance(calculation_supported, bool):
        raise TaxRuleSchemaError("State capital-gain calculation support must be boolean.")
    exclusion_percent = _percentage(capital.get("exclusion_percent", 0), "State capital-gain exclusion")
    fixed_deduction = ZERO
    deduction_percent = ZERO
    if treatment is CapitalGainTreatment.DEDUCTION_THEN_ORDINARY_SCHEDULE:
        deduction = capital.get("deduction")
        alternatives = deduction.get("greater_of") if isinstance(deduction, dict) else None
        if not isinstance(alternatives, list):
            raise TaxRuleSchemaError("State capital-gain deduction alternatives are incomplete.")
        for alternative in alternatives:
            if not isinstance(alternative, dict):
                raise TaxRuleSchemaError("State capital-gain deduction alternative is invalid.")
            if "fixed_amount" in alternative:
                fixed_deduction = max(
                    fixed_deduction, _deduction_amount(alternative["fixed_amount"], "state capital-gain")
                )
            if "percent_of_net_capital_gain" in alternative:
                deduction_percent = max(
                    deduction_percent,
                    _percentage(alternative["percent_of_net_capital_gain"], "State capital-gain deduction"),
                )
    return CapitalGainRule(treatment, calculation_supported, exclusion_percent, fixed_deduction, deduction_percent)


def _percentage(value: object, label: str) -> Decimal:
    if not isinstance(value, (int, float)):
        raise TaxRuleSchemaError(f"{label} must be numeric.")
    parsed = _decimal(value) / Decimal("100")
    if parsed < ZERO or parsed > Decimal("1"):
        raise TaxRuleSchemaError(f"{label} must be between 0 and 100.")
    return parsed


def _bracket_schedule(value: object, label: str) -> BracketSchedule:
    if not isinstance(value, list) or not value:
        raise TaxRuleSchemaError(f"{label.capitalize()} schedule must include at least one bracket.")
    bands: list[BracketBand] = []
    previous: Decimal | None = None
    for item in value:
        if not isinstance(item, dict):
            raise TaxRuleSchemaError(f"{label.capitalize()} schedule contains an invalid bracket.")
        upper_bound = item.get("bracket")
        if upper_bound is not None and not isinstance(upper_bound, (int, float)):
            raise TaxRuleSchemaError(f"{label.capitalize()} schedule has an invalid bracket boundary.")
        if not isinstance(item.get("rate"), (int, float)):
            raise TaxRuleSchemaError(f"{label.capitalize()} schedule has an invalid rate.")
        parsed_bound = _decimal(upper_bound) if upper_bound is not None else None
        if parsed_bound is not None and (parsed_bound < ZERO or (previous is not None and parsed_bound <= previous)):
            raise TaxRuleSchemaError(f"{label.capitalize()} schedule boundaries must be increasing.")
        if parsed_bound is None and item is not value[-1]:
            raise TaxRuleSchemaError(f"{label.capitalize()} schedule may only have an open-ended final bracket.")
        bands.append(BracketBand(parsed_bound, _decimal(item["rate"]) / Decimal("100")))
        previous = parsed_bound
    if bands[-1].upper_bound is not None:
        raise TaxRuleSchemaError(f"{label.capitalize()} schedule must have an open-ended final bracket.")
    return BracketSchedule(tuple(bands))


def _deduction_amount(value: object, jurisdiction: str) -> Decimal:
    if not isinstance(value, (int, float)):
        raise TaxRuleSchemaError(f"{jurisdiction.capitalize()} standard deduction is invalid.")
    return max(_decimal(value), ZERO)


def _federal_dependent_credit(federal: dict[str, object]) -> FederalDependentCreditRule:
    credits = federal.get("credits")
    child = credits.get("child_tax_credit") if isinstance(credits, dict) else None
    other = credits.get("credit_for_other_dependents") if isinstance(credits, dict) else None
    phaseout = child.get("phaseout") if isinstance(child, dict) else None
    thresholds = phaseout.get("modified_agi_threshold") if isinstance(phaseout, dict) else None
    if (
        not isinstance(child, dict)
        or not isinstance(other, dict)
        or not isinstance(phaseout, dict)
        or not isinstance(thresholds, dict)
    ):
        raise TaxRuleSchemaError("Federal dependent-credit rules are incomplete.")
    return FederalDependentCreditRule(
        _decimal(child.get("maximum_per_qualifying_child")),
        _decimal(other.get("maximum_per_qualifying_dependent")),
        _decimal(thresholds.get("married_filing_jointly")),
        _decimal(thresholds.get("all_other_filing_statuses")),
        _decimal(phaseout.get("reduction_per_1000_or_fraction")),
    )
