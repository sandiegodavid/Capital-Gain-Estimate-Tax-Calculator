"""Pure renderers for calculated tax output and benefit summaries."""

from __future__ import annotations

from decimal import Decimal

from ..tax_calculation import MappedRate, TaxRateMapping
from ..tax_estimate import TaxFormula
from .html import currency, escape, rule_label


def render_federal_dependent_credit_estimate(credit_estimate, derived_magi: Decimal) -> str:
    phaseout = (
        f" MAGI phaseout reduced the estimate by {currency(credit_estimate.phaseout_reduction)}."
        if credit_estimate.phaseout_reduction
        else ""
    )
    return f'<aside class="tax-credit-summary" role="note"><strong>Estimated federal child/dependent credits: −{currency(credit_estimate.amount)}</strong><span>Based on confirmed eligible dependents and a derived planning MAGI of {currency(derived_magi)} (other ordinary taxable income plus imported net capital gains).{phaseout} This nonrefundable estimate is shown separately and is not deducted from the gains-only tax estimate; your total federal tax liability can limit it.</span></aside>'


def render_state_dependent_benefits(benefits, state_name: str | None) -> str:
    if not benefits.lines:
        return ""
    name = state_name or "state"
    items = []
    for line in benefits.lines:
        label = rule_label(line.id)
        if line.outcome == "calculated":
            items.append(f"{label}: {currency(line.applied_amount)} deduction applied to state taxable income.")
        elif line.outcome == "potential_only":
            credit = f"up to {currency(line.potential_amount)}"
            cap = f" (modeled liability cap: {currency(line.applied_amount)})" if line.applied_amount else ""
            items.append(
                f"{label}: {credit} nonrefundable credit shown separately, not deducted from the gains-only estimate{cap}."
            )
        elif line.outcome == "requires_more_inputs":
            items.append(f"{label}: requires more state eligibility information. {line.explanation}")
        else:
            qualifier = " Uses provisional prior-year parameters." if line.provisional else ""
            items.append(f"{label}: informational only; not calculated. {line.explanation}{qualifier}")
    return f'<aside class="tax-credit-summary" role="note"><strong>Estimated {escape(name)} child/dependent benefits</strong><span>{escape(" ".join(items))}</span></aside>'


def render_rate_cards(
    mapping: TaxRateMapping | None,
    ordinary_income: Decimal,
    short_term_gain: Decimal,
    long_term_gain: Decimal,
    estimate,
    formula: TaxFormula | None,
) -> str:
    if mapping is None:
        return '<div class="mapped-rates"><article><p>Mapped tax rates</p><strong>Unavailable</strong><small>No applicable local tax schedule is available.</small></article></div>'
    ordinary_end = formula.federal_short_term.closing_income if formula else ordinary_income + short_term_gain
    long_term_end = formula.federal_long_term.closing_income if formula else ordinary_end + long_term_gain
    state_end = formula.state.closing_income if formula else ordinary_end + long_term_gain
    state_card = (
        _rate_card("State tax rate", mapping.state, state_end, estimate.state)
        if formula and formula.state_calculation_supported
        else "<article><p>State tax rate</p><strong>Unavailable</strong><small>The selected jurisdiction cannot be calculated exactly from the bundled rules.</small></article>"
    )
    cards = (
        _rate_card(
            "Federal ordinary / short-term rate", mapping.federal_short_term, ordinary_end, estimate.federal_short_term
        ),
        _rate_card("Federal long-term rate", mapping.federal_long_term, long_term_end, estimate.federal_long_term),
        state_card,
    )
    return f'<div class="mapped-rates">{"".join(cards)}</div>'


def render_formula_button(formula: TaxFormula | None) -> str:
    if formula is None:
        return ""
    lines = [formula.federal_short_term, formula.federal_long_term]
    if formula.state_calculation_supported:
        lines.append(formula.state)
    rows = "".join(_formula_row(line, formula) for line in lines)
    return f"""<style>.tax-formula-dialog th:first-child,.tax-formula-dialog td:first-child{{position:sticky;left:0;z-index:1;background:#fff}}.tax-formula-dialog th:first-child{{z-index:2;background:#f8fafc}}</style><div class="formula-action"><button id="show-tax-formula" type="button">See exact formula</button></div>
    <dialog id="tax-formula-dialog" class="tax-formula-dialog"><div class="dialog-heading"><div><h2>Exact tax formula</h2><p>Bundled federal and supported state rules are applied by filing status.</p></div><button id="close-tax-formula" type="button" aria-label="Close">×</button></div><div class="formula-note">Short- and long-term carryover losses first offset their matching gain type. Any combined excess reduces ordinary income up to $3,000, or $1,500 for married filing separately. State exclusions encoded as directly calculable rules are applied before state brackets.</div><div class="table-wrap"><table><thead><tr><th>Tax type</th><th>Total taxable income</th><th>Applicable bracket formula</th><th>Tax amount</th></tr></thead><tbody>{rows}</tbody></table></div></dialog>
    <script>(()=>{{const open=document.getElementById("show-tax-formula"),dialog=document.getElementById("tax-formula-dialog"),close=document.getElementById("close-tax-formula");if(open&&dialog&&close){{open.addEventListener("click",()=>dialog.showModal());close.addEventListener("click",()=>dialog.close());}}}})();</script>"""


def _rate_card(label: str, mapped_rate: MappedRate, taxable_income: Decimal, tax_amount: Decimal) -> str:
    bracket = (
        f" through {currency(mapped_rate.bracket_upper_bound)}"
        if mapped_rate.bracket_upper_bound is not None
        else " in the top reported bracket"
    )
    return f"<article><p>{escape(label)}</p><strong>{mapped_rate.rate * 100:g}%</strong><small>Highest bracket reached at taxable income of {currency(taxable_income)}{bracket}.</small><small>Tax from this type: {currency(tax_amount)}</small></article>"


def _formula_row(line, formula: TaxFormula) -> str:
    if line.label == "Federal long-term":
        taxable_gain = line.closing_income - line.opening_income
        taxable_income = f"max({currency(formula.long_term_gain)} long-term gain − {currency(formula.remaining_standard_deduction)} remaining standard deduction, $0) = {currency(taxable_gain)}; stacked above {currency(line.opening_income)} ordinary taxable income"
        if formula.remaining_standard_deduction == Decimal("0"):
            taxable_income = f"{currency(formula.long_term_gain)} long-term gain stacked above {currency(line.opening_income)} ordinary taxable income"
    elif line.label == "State":
        taxable_income = f"{currency(formula.other_ordinary_income)} other ordinary income + {currency(formula.state_short_term_gain)} taxable short-term gain + {currency(formula.state_long_term_gain)} taxable long-term gain − {currency(formula.state_standard_deduction)} state standard deduction − {currency(formula.state_dependent_deduction)} state dependent deduction = {currency(line.closing_income)}"
    else:
        taxable_income = f"max({currency(formula.other_ordinary_income)} other ordinary income + {currency(formula.short_term_gain)} short-term gain − {currency(formula.federal_standard_deduction)} federal standard deduction, $0) = {currency(line.closing_income)}"
    bracket_formula = (
        " + ".join(
            f"({currency(component.taxable_amount)} × {component.rate * 100:g}%)" for component in line.components
        )
        or "$0.00"
    )
    return f"<tr><td>{escape(line.label)}</td><td>{escape(taxable_income)}</td><td>{escape(bracket_formula)}</td><td>{currency(line.tax_amount)}</td></tr>"
