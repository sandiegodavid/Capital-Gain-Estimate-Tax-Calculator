"""Evaluate only explicitly modelled state child and dependent benefits."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from .models import ZERO
from .tax_domain import (
    BenefitContext,
    BenefitOutcomeKind,
    BenefitType,
    CalculationMethod,
    DependentBenefitRule,
    EligibilityBasis,
)


class BenefitCalculator(Protocol):
    def supports(self, rule: DependentBenefitRule) -> bool: ...
    def calculate(self, rule: DependentBenefitRule, context: BenefitContext) -> "StateDependentBenefitLine": ...


class DependentBenefitRuleProvider(Protocol):
    @property
    def dependent_benefit_rules(self) -> tuple[DependentBenefitRule, ...]: ...


class BenefitAssumptions(Protocol):
    @property
    def filing_status(self) -> str: ...

    @property
    def qualified_children(self) -> int: ...

    @property
    def other_dependents(self) -> int: ...


class FixedBenefitCalculator:
    """Calculates fixed per-dependent rules without interpreting YAML."""

    def supports(self, rule: DependentBenefitRule) -> bool:
        return rule.calculation_method in {CalculationMethod.FIXED_PER_DEPENDENT, CalculationMethod.FIXED_PER_CHILD}

    def calculate(self, rule: DependentBenefitRule, context: BenefitContext) -> "StateDependentBenefitLine":
        if context.filing_status not in rule.filing_statuses:
            return StateDependentBenefitLine(
                rule.identifier,
                rule.benefit_type.value,
                BenefitOutcomeKind.REQUIRES_MORE_INPUTS.value,
                explanation="This filing status is not eligible.",
                provisional=rule.provisional,
            )
        count: int | None
        if rule.eligibility_basis is EligibilityBasis.FEDERAL_CONFIRMED_DEPENDENT:
            count = context.qualified_children + context.other_dependents
        else:
            key = {
                EligibilityBasis.STATE_ELIGIBLE_DEPENDENT: "state_eligible_dependents",
                EligibilityBasis.CHILD_UNDER_AGE: "children_under_age",
                EligibilityBasis.ADOPTED_CHILD: "adopted_children",
                EligibilityBasis.COLLEGE_DEPENDENT: "college_dependents",
            }[rule.eligibility_basis]
            count = context.state_eligibility.get(key)
        if count is None:
            return StateDependentBenefitLine(
                rule.identifier,
                rule.benefit_type.value,
                BenefitOutcomeKind.REQUIRES_MORE_INPUTS.value,
                explanation="Required state eligibility information is missing.",
                provisional=rule.provisional,
            )
        amount = max(0, count) * (rule.amount or ZERO)
        outcome = (
            BenefitOutcomeKind.CALCULATED
            if rule.benefit_type is BenefitType.DEDUCTION
            else BenefitOutcomeKind.POTENTIAL_ONLY
        )
        return StateDependentBenefitLine(
            rule.identifier,
            rule.benefit_type.value,
            outcome.value,
            amount,
            amount if outcome is BenefitOutcomeKind.CALCULATED else ZERO,
            provisional=rule.provisional,
        )


BENEFIT_CALCULATORS: tuple[BenefitCalculator, ...] = (FixedBenefitCalculator(),)


@dataclass(frozen=True)
class StateDependentBenefitLine:
    id: str
    benefit_type: str
    outcome: str
    potential_amount: Decimal = ZERO
    applied_amount: Decimal = ZERO
    phaseout_reduction: Decimal = ZERO
    explanation: str = ""
    provisional: bool = False


@dataclass(frozen=True)
class StateDependentBenefitEstimate:
    deduction: Decimal = ZERO
    potential_nonrefundable_credit: Decimal = ZERO
    potential_refundable_credit: Decimal = ZERO
    applied_nonrefundable_credit: Decimal = ZERO
    phaseout_reduction: Decimal = ZERO
    lines: tuple[StateDependentBenefitLine, ...] = ()


def estimate_state_dependent_benefits(
    rules: DependentBenefitRuleProvider,
    assumptions: BenefitAssumptions,
    income_context: dict[str, Decimal],
    state_eligibility: dict[str, int],
    state_tax_liability: Decimal | None = None,
) -> StateDependentBenefitEstimate:
    """Evaluate a declared rule; amounts alone never authorize calculation."""
    typed_rules = rules.dependent_benefit_rules
    if typed_rules:
        eligibility = dict(state_eligibility)
        # The dashboard currently asks only for confirmed federal dependent
        # counts.  They are the temporary planning proxy for a state-eligible
        # dependent count, while age/adoption/college requirements remain
        # separate, required inputs.
        eligibility.setdefault(
            "state_eligible_dependents",
            assumptions.qualified_children + assumptions.other_dependents,
        )
        context = BenefitContext(
            assumptions.filing_status,
            assumptions.qualified_children,
            assumptions.other_dependents,
            eligibility,
            income_context,
            state_tax_liability,
        )
        lines: list[StateDependentBenefitLine] = []
        deduction = nonrefundable = refundable = applied_nonrefundable = ZERO
        for rule in typed_rules:
            calculator = next(
                (
                    candidate
                    for candidate in BENEFIT_CALCULATORS
                    if rule.calculation_supported and candidate.supports(rule)
                ),
                None,
            )
            line = (
                calculator.calculate(rule, context)
                if calculator
                else StateDependentBenefitLine(
                    rule.identifier,
                    rule.benefit_type.value,
                    BenefitOutcomeKind.UNSUPPORTED.value,
                    explanation=rule.unsupported_reason,
                    provisional=rule.provisional,
                )
            )
            if rule.benefit_type is BenefitType.DEDUCTION and line.outcome == "calculated":
                deduction += line.applied_amount
            elif rule.benefit_type is BenefitType.NONREFUNDABLE_CREDIT and line.outcome == "potential_only":
                nonrefundable += line.potential_amount
                if state_tax_liability is not None:
                    applied = min(line.potential_amount, max(state_tax_liability - applied_nonrefundable, ZERO))
                    applied_nonrefundable += applied
                    line = StateDependentBenefitLine(
                        line.id,
                        line.benefit_type,
                        line.outcome,
                        line.potential_amount,
                        applied,
                        line.phaseout_reduction,
                        line.explanation,
                        line.provisional,
                    )
            elif rule.benefit_type is BenefitType.REFUNDABLE_CREDIT and line.outcome == "potential_only":
                refundable += line.potential_amount
            lines.append(line)
        return StateDependentBenefitEstimate(
            deduction, nonrefundable, refundable, applied_nonrefundable, ZERO, tuple(lines)
        )
    return StateDependentBenefitEstimate()
