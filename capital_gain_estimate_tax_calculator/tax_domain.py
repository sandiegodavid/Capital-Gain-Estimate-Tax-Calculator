"""Typed, framework-free values used by the tax calculation domain."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Mapping


class BenefitType(str, Enum):
    DEDUCTION = "deduction"
    NONREFUNDABLE_CREDIT = "nonrefundable_credit"
    REFUNDABLE_CREDIT = "refundable_credit"


class FilingStatus(str, Enum):
    SINGLE = "single"
    MARRIED_FILING_JOINTLY = "married_filing_jointly"
    MARRIED_FILING_SEPARATELY = "married_filing_separately"
    HEAD_OF_HOUSEHOLD = "head_of_household"
    QUALIFYING_SURVIVING_SPOUSE = "qualifying_surviving_spouse"


class BenefitOutcomeKind(str, Enum):
    CALCULATED = "calculated"
    POTENTIAL_ONLY = "potential_only"
    REQUIRES_MORE_INPUTS = "requires_more_inputs"
    UNSUPPORTED = "unsupported"


class EligibilityBasis(str, Enum):
    STATE_ELIGIBLE_DEPENDENT = "state_eligible_dependent"
    FEDERAL_CONFIRMED_DEPENDENT = "federal_confirmed_dependent"
    CHILD_UNDER_AGE = "child_under_age"
    ADOPTED_CHILD = "adopted_child"
    COLLEGE_DEPENDENT = "college_dependent"


class CalculationMethod(str, Enum):
    FIXED_PER_DEPENDENT = "fixed_per_dependent"
    FIXED_PER_CHILD = "fixed_per_child"


class IncomeMeasure(str, Enum):
    FEDERAL_AGI = "federal_agi"
    STATE_AGI = "state_agi"
    MAGI = "magi"
    TAXABLE_INCOME = "taxable_income"
    NOT_APPLICABLE = "not_applicable"


class CapitalGainTreatment(str, Enum):
    ORDINARY_SCHEDULE = "ordinary_schedule"
    PERCENTAGE_EXCLUSION_THEN_ORDINARY_SCHEDULE = "percentage_exclusion_then_ordinary_schedule"
    FULL_SUBTRACTION = "full_subtraction"
    DEDUCTION_THEN_ORDINARY_SCHEDULE = "deduction_then_ordinary_schedule"
    ORDINARY_SCHEDULE_WITH_CONDITIONAL_EXCLUSION = "ordinary_schedule_with_conditional_exclusion"
    ORDINARY_SCHEDULE_WITH_CONDITIONAL_DEDUCTION = "ordinary_schedule_with_conditional_deduction"
    ORDINARY_SCHEDULE_WITH_CONDITIONAL_SUBTRACTION = "ordinary_schedule_with_conditional_subtraction"
    ORDINARY_SCHEDULE_PLUS_NET_INVESTMENT_INCOME_TAX = "ordinary_schedule_plus_net_investment_income_tax"
    ORDINARY_NONBUSINESS_INCOME_FORMULA = "ordinary_nonbusiness_income_formula"
    CAPITAL_GAINS_EXCISE_ONLY = "capital_gains_excise_only"
    ALTERNATIVE_EXCLUSION_THEN_ORDINARY_SCHEDULE = "alternative_exclusion_then_ordinary_schedule"
    ORDINARY_SCHEDULE_PLUS_INCOME_SURCHARGE = "ordinary_schedule_plus_income_surcharge"
    SEPARATE_SHORT_TERM_RATE = "separate_short_term_rate"
    SEPARATE_LONG_TERM_SCHEDULE = "separate_long_term_schedule"
    SEPARATE_INCOME_CLASS_AT_ORDINARY_RATE = "separate_income_class_at_ordinary_rate"
    ORDINARY_SCHEDULE_PLUS_SURTAX = "ordinary_schedule_plus_surtax"
    PERCENTAGE_DEDUCTION_THEN_ORDINARY_FORMULA = "percentage_deduction_then_ordinary_formula"


class TaxRuleSchemaError(ValueError):
    """A bundled rule cannot be safely interpreted."""


@dataclass(frozen=True)
class FederalDependentCreditRule:
    child_credit_amount: Decimal = Decimal("0")
    other_dependent_credit_amount: Decimal = Decimal("0")
    joint_phaseout_threshold: Decimal = Decimal("0")
    other_phaseout_threshold: Decimal = Decimal("0")
    reduction_per_thousand: Decimal = Decimal("0")


@dataclass(frozen=True)
class BracketBand:
    upper_bound: Decimal | None
    rate: Decimal


@dataclass(frozen=True)
class BracketSchedule:
    bands: tuple[BracketBand, ...]


@dataclass(frozen=True)
class TaxCalculationRules:
    """Validated schedules and deductions required by the estimate engine."""

    federal_ordinary: BracketSchedule
    federal_long_term: BracketSchedule
    state_ordinary: BracketSchedule
    federal_standard_deduction: Decimal
    state_standard_deduction: Decimal


@dataclass(frozen=True)
class CapitalGainRule:
    treatment: CapitalGainTreatment
    calculation_supported: bool
    exclusion_percent: Decimal = Decimal("0")
    fixed_deduction: Decimal = Decimal("0")
    deduction_percent: Decimal = Decimal("0")


@dataclass(frozen=True)
class TaxRuleDetail:
    label: str
    value: str


@dataclass(frozen=True)
class TaxRuleCard:
    title: str
    details: tuple[TaxRuleDetail, ...]


@dataclass(frozen=True)
class TaxRuleBracketTable:
    title: str
    schedule: BracketSchedule


@dataclass(frozen=True)
class JurisdictionRuleDisplay:
    bracket_tables: tuple[TaxRuleBracketTable, ...]
    standard_deduction: Decimal | None
    standard_deduction_details: tuple[TaxRuleDetail, ...]
    credits: tuple[TaxRuleCard, ...]


@dataclass(frozen=True)
class TaxRuleDisplay:
    federal: JurisdictionRuleDisplay
    state: JurisdictionRuleDisplay


@dataclass(frozen=True)
class DependentBenefitRule:
    identifier: str
    benefit_type: BenefitType
    eligibility_basis: EligibilityBasis
    calculation_method: CalculationMethod | None
    amount: Decimal | None
    income_measure: IncomeMeasure
    filing_statuses: frozenset[str]
    calculation_supported: bool
    unsupported_reason: str
    source_tax_year: int
    provisional: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, object], tax_year: int) -> "DependentBenefitRule":
        required = {
            "id",
            "benefit_type",
            "eligibility_basis",
            "calculation",
            "income_measure",
            "filing_statuses",
            "calculation_supported",
            "source_tax_year",
            "status",
        }
        missing = sorted(required - value.keys())
        if missing:
            raise TaxRuleSchemaError(f"Dependent benefit is missing required fields: {', '.join(missing)}.")
        try:
            benefit_type = BenefitType(str(value["benefit_type"]))
            basis = EligibilityBasis(str(value["eligibility_basis"]))
            measure = IncomeMeasure(str(value["income_measure"]))
        except ValueError as exc:
            raise TaxRuleSchemaError(
                f"Dependent benefit {value.get('id', '<unknown>')} has an invalid enum value."
            ) from exc
        calculation = value["calculation"]
        if not isinstance(calculation, Mapping):
            raise TaxRuleSchemaError(f"Dependent benefit {value['id']} calculation must be an object.")
        try:
            method = CalculationMethod(str(calculation["method"])) if calculation.get("method") is not None else None
            amount = Decimal(str(calculation["amount"])) if calculation.get("amount") is not None else None
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise TaxRuleSchemaError(f"Dependent benefit {value['id']} has an invalid calculation.") from exc
        statuses = value["filing_statuses"]
        if not isinstance(statuses, list) or not all(isinstance(item, str) for item in statuses):
            raise TaxRuleSchemaError(f"Dependent benefit {value['id']} filing_statuses must be strings.")
        supported = value["calculation_supported"]
        if not isinstance(supported, bool) or (supported and (method is None or amount is None)):
            raise TaxRuleSchemaError(
                f"Calculable dependent benefit {value['id']} needs boolean support, a method, and an amount."
            )
        source_year = value["source_tax_year"]
        if not isinstance(source_year, int):
            raise TaxRuleSchemaError(f"Dependent benefit {value['id']} source_tax_year must be an integer.")
        return cls(
            str(value["id"]),
            benefit_type,
            basis,
            method,
            amount,
            measure,
            frozenset(statuses),
            supported,
            str(value.get("unsupported_reason", "This benefit cannot be calculated from the bundled rule.")),
            source_year,
            source_year != tax_year or value["status"] == "provisional",
        )


@dataclass(frozen=True)
class BenefitContext:
    filing_status: str
    qualified_children: int
    other_dependents: int
    state_eligibility: Mapping[str, int]
    income_context: Mapping[str, Decimal]
    state_tax_liability: Decimal | None = None
