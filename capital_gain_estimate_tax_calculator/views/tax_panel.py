"""Pure HTML rendering for the estimated-tax panel."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..dashboard_selection import DashboardSelection
from ..tax_calculation import TaxRateMapping
from ..tax_estimate import FILING_STATUSES, US_STATES, FederalDependentCreditEstimate, TaxAssumptions, TaxFormula
from ..tax_rules import TaxRuleBundle
from .dashboard_details import source_selection_inputs
from .html import currency, escape
from .tax_output import (
    render_federal_dependent_credit_estimate,
    render_formula_button,
    render_rate_cards,
    render_state_dependent_benefits,
)
from .tax_rules import render_tax_rules_modal


@dataclass(frozen=True)
class TaxPanelViewModel:
    """Display-ready tax calculation and profile values for one dashboard."""

    selection: DashboardSelection
    assumptions: TaxAssumptions
    rules: TaxRuleBundle
    formula: TaxFormula
    short_term_gain: Decimal
    long_term_gain: Decimal
    derived_magi: Decimal
    dependent_credit_estimate: FederalDependentCreditEstimate
    rate_mapping: TaxRateMapping
    state_name: str | None
    federal_payment_url: str | None
    state_payment_url: str | None


def render_tax_panel(view: TaxPanelViewModel) -> str:
    """Render a tax panel without loading rules or performing calculations."""
    formula = view.formula
    estimate = formula.estimate
    assumptions = view.assumptions
    rules = view.rules
    state_options = "".join(
        f'<option value="{code}" {"selected" if code == assumptions.state_code else ""}>{escape(name)}</option>'
        for code, name in US_STATES
    )
    state_requirement = f'<p class="state-rule-note">{escape(rules.state_notice)}</p>' if rules.state_notice else ""
    federal_payment_button = _payment_button(view.federal_payment_url, "Pay federal estimated tax")
    state_payment = _payment_button(view.state_payment_url, f"Pay {view.state_name} estimated tax", " secondary")
    formula_summary = (
        '<div class="tax-formula-summary"><div class="tax-actions">'
        f"{federal_payment_button}{state_payment}</div>{render_formula_button(formula)}"
        f"{render_tax_rules_modal(rules)}</div>"
    )
    fields = _tax_fields(assumptions, state_options)
    state_estimate = currency(estimate.state) if rules.state_calculation_supported else "Unavailable"
    rate_cards = render_rate_cards(
        view.rate_mapping,
        assumptions.other_ordinary_taxable_income,
        view.short_term_gain,
        view.long_term_gain,
        estimate,
        formula,
    )
    credit_summary = (
        render_federal_dependent_credit_estimate(view.dependent_credit_estimate, view.derived_magi)
        if assumptions.qualified_children + assumptions.other_dependents
        else ""
    )
    selection_inputs = source_selection_inputs(view.selection)
    return f'''<style>
    .tax-formula-summary {{ display:flex; justify-content:center; align-items:center; gap:10px; flex-wrap:wrap; padding:12px 18px; border-top:1px solid #d9e2ec; background:#fff }}
    .tax-formula-summary .formula-action,.tax-formula-summary .tax-rules-action {{ display:contents }} .tax-formula-summary .formula-action button,.tax-formula-summary .tax-rules-action button {{ min-height:34px; margin:0; padding:6px 12px; border:1px solid #9ed5bc; border-radius:7px; background:#e8f5ef; color:#087f5b; font-size:13px; font-weight:700; white-space:nowrap }} .tax-formula-summary .tax-rules-action button {{ border-color:#b6c8d8; background:#f1f6fa; color:#315d7d }} .tax-formula-summary .tax-actions {{ display:flex; gap:10px; padding:0 }} .tax-formula-summary .pay-button {{ min-height:38px; margin:0; padding:8px 15px; border:0; border-radius:7px; background:#087f5b; color:white; font-size:14px; font-weight:700; white-space:nowrap }} .tax-formula-summary .pay-button.secondary {{ background:#1f5f8b }}
    .tax-form {{ grid-template-columns:repeat(4,minmax(160px,1fr)); align-items:end }} .tax-field {{ min-width:0 }} .tax-field-second-row {{ grid-row:2 }} .tax-field-heading {{ display:flex; align-items:center; gap:5px; min-height:18px }} .tax-field-heading label {{ display:block; white-space:nowrap }} .tax-field input,.tax-field select {{ width:100% }} #ordinary-income::-webkit-inner-spin-button,#ordinary-income::-webkit-outer-spin-button,#short-term-carryover-loss::-webkit-inner-spin-button,#short-term-carryover-loss::-webkit-outer-spin-button,#long-term-carryover-loss::-webkit-inner-spin-button,#long-term-carryover-loss::-webkit-outer-spin-button {{ appearance:none; margin:0 }} #ordinary-income,#short-term-carryover-loss,#long-term-carryover-loss {{ -moz-appearance:textfield }} .field-help {{ position:relative; flex:0 0 auto }} .field-help summary {{ display:grid; place-items:center; width:16px; height:16px; border:1px solid #7e9ab3; border-radius:50%; color:#315d7d; cursor:pointer; font-size:11px; font-weight:800; list-style:none }} .field-help summary::-webkit-details-marker {{ display:none }} .field-help[open] summary {{ background:#315d7d; color:#fff }} .field-help p {{ position:absolute; z-index:5; top:20px; width:min(240px,calc(100vw - 32px)); margin:0; padding:9px 10px; border:1px solid #bfd7ea; border-radius:7px; background:#f8fbfe; box-shadow:0 5px 16px #102a4322; color:#315d7d; font-size:12px; font-weight:500; line-height:1.35 }} .field-help-start p {{ left:-8px }} .field-help-end p {{ right:0 }}
    .tax-rules-dialog {{ width:min(1000px,95vw); max-height:90vh; padding:0; border:0; border-radius:14px; color:#102a43; box-shadow:0 24px 70px #102a4355 }} .tax-rules-dialog::backdrop {{ background:#102a4388 }} .tax-rules-body {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; padding:18px 22px 24px; overflow:auto }} .jurisdiction-rules {{ min-width:0 }} .jurisdiction-rules h3 {{ margin:0 0 14px }} .jurisdiction-rules h4 {{ margin:16px 0 7px }} .jurisdiction-rules table {{ font-size:13px }} .jurisdiction-rules th,.jurisdiction-rules td {{ padding:7px 9px }} .jurisdiction-rules ul {{ margin:6px 0; padding-left:19px }} .credit-rule {{ margin:8px 0; padding:10px; border:1px solid #d9e2ec; border-radius:7px; background:#f8fafc }} .credit-rule h4 {{ margin:0 0 5px }} .empty-rule {{ color:#627d98 }}
    .tax-form-action {{ min-height:38px; grid-column:4; grid-row:2; width:100% }}
    .tax-estimate-stale {{ margin:0; padding:16px 18px; border-top:1px solid var(--line); color:var(--muted); font-size:13px }}
    .tax-estimate-stale-action {{ min-height:0; padding:0; border:0; border-radius:0; background:transparent; color:inherit; font:inherit; font-weight:700; text-decoration:underline; text-underline-offset:2px }} .tax-estimate-stale-action:hover {{ color:var(--blue) }}
    .tax-credit-summary {{ display:grid; gap:3px; padding:13px 18px; border-top:1px solid var(--line); background:#f2f8fc; color:#315d7d; font-size:13px }} .tax-credit-summary strong {{ color:var(--ink) }}
    @media(max-width:900px) {{ .tax-form {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .tax-field-second-row,.tax-form-action {{ grid-row:auto }} .tax-form-action {{ grid-column:2; width:100%; }} .tax-field:nth-of-type(2) .field-help p,.tax-field:nth-of-type(6) .field-help p {{ right:0; left:auto }} .tax-field:nth-of-type(3) .field-help p,.tax-field:nth-of-type(5) .field-help p {{ right:auto; left:-8px }} }}
    @media(max-width:800px) {{ .tax-formula-summary {{ align-items:stretch }} .tax-formula-summary .formula-action button,.tax-formula-summary .tax-rules-action button {{ width:100% }} .tax-rules-body {{ grid-template-columns:1fr }} }}
    </style><section class="panel tax-panel">
    <div class="panel-heading"><h2>Estimated Tax</h2><span>Planning estimate — not tax advice · No liability assumed</span></div>
    <form id="tax-estimate-form" method="get" action="/dashboard" class="tax-form"><input type="hidden" name="year" value="{view.selection.year}"><input type="hidden" name="source" value="{escape(view.selection.source_dir)}"><input type="hidden" name="output" value="{escape(view.selection.output_dir)}">{selection_inputs}{fields}<button class="tax-form-action" type="submit">Update estimate</button></form>
    <div id="tax-estimate-output">{rate_cards}{credit_summary}{render_state_dependent_benefits(formula.state_dependent_benefits, view.state_name)}<div class="tax-results"><article><p>Federal estimate</p><strong>{currency(estimate.federal)}</strong></article><article><p>State estimate{f" · {assumptions.state_code}" if assumptions.state_code else ""}</p><strong>{state_estimate}</strong></article><article><p>Estimated total calculated tax</p><strong>{currency(estimate.total)}</strong></article></div>{formula_summary}{state_requirement}<p class="tax-note">Calculated from the bundled {view.selection.year} jurisdiction rules. Federal and state credits shown separately are not deducted from this gains-only tax estimate. Out of scope: the refundable Additional Child Tax Credit (ACTC), Earned Income Tax Credit (EITC), and special rules marked unsupported in the local YAML.</p></div>
    <p id="tax-estimate-stale" class="tax-estimate-stale" role="status" hidden>Estimate inputs changed. Click <button class="tax-estimate-stale-action" type="submit" form="tax-estimate-form">Update estimate</button> to calculate with these values.</p>
    </section>'''


def _payment_button(url: str | None, label: str, class_suffix: str = "") -> str:
    if not url:
        return ""
    return (
        f'<a class="pay-button{class_suffix}" href="{escape(url)}" target="_blank" rel="noopener">{escape(label)}</a>'
    )


def _tax_fields(assumptions: TaxAssumptions, state_options: str) -> str:
    return "".join(
        (
            _tax_field(
                "State residence",
                "state-residence",
                f'<select id="state-residence" name="state">{state_options}</select>',
                "Your state of legal residence for this estimate. Local taxes and multi-state residency are not included.",
            ),
            _tax_field(
                "Filing status",
                "filing-status",
                f'<select id="filing-status" name="filing_status">{_filing_options(assumptions)}</select>',
                "Choose the status you expect to use for this tax year. It determines the brackets and standard deduction.",
                "end",
            ),
            _tax_field(
                "CTC-eligible children",
                "qualified-children",
                f'<input id="qualified-children" name="qualified_children" type="number" min="0" max="99" step="1" value="{assumptions.qualified_children}">',
                "Children you confirm meet every Child Tax Credit eligibility requirement for this tax year, including the age, relationship, residency, dependent, and Social Security number requirements.",
                "end",
            ),
            _tax_field(
                "Other credit-eligible dependents",
                "other-dependents",
                f'<input id="other-dependents" name="other_dependents" type="number" min="0" max="99" step="1" value="{assumptions.other_dependents}">',
                "Dependents you confirm are eligible for the federal Credit for Other Dependents. They are not counted as Child Tax Credit-eligible children.",
                "end",
            ),
            _tax_field(
                "Other ordinary taxable income ($)",
                "ordinary-income",
                f'<input id="ordinary-income" name="other_ordinary_taxable_income" type="number" min="0" step="1" value="{assumptions.other_ordinary_taxable_income:g}">',
                "Include all other expected taxable income: wages; taxable interest and dividends; retirement or taxable Social Security income; business or self-employment income; rental or K-1 income; income not included in the imported realized-gains files; and any other taxable income. Do not include capital gains or losses shown in the report. The app adds imported net capital gains to this amount for its planning MAGI proxy; it does not collect MAGI adjustments.",
                "end",
                "tax-field-second-row",
            ),
            _tax_field(
                "Short-term loss carryover ($)",
                "short-term-carryover-loss",
                f'<input id="short-term-carryover-loss" name="short_term_carryover_loss" type="number" min="0" step="1" value="{assumptions.short_term_carryover_loss:g}">',
                "Unused short-term capital loss from prior tax years. It offsets short-term gains first; remaining loss is subject to the annual ordinary-income offset limit.",
                "end",
                "tax-field-second-row",
            ),
            _tax_field(
                "Long-term loss carryover ($)",
                "long-term-carryover-loss",
                f'<input id="long-term-carryover-loss" name="long_term_carryover_loss" type="number" min="0" step="1" value="{assumptions.long_term_carryover_loss:g}">',
                "Unused long-term capital loss from prior tax years. It offsets long-term gains first; remaining loss is subject to the annual ordinary-income offset limit.",
                "start",
                "tax-field-second-row",
            ),
        )
    )


def _filing_options(assumptions: TaxAssumptions) -> str:
    return "".join(
        f'<option value="{code}" {"selected" if code == assumptions.filing_status else ""}>{escape(label)}</option>'
        for code, label in FILING_STATUSES
    )


def _tax_field(
    label: str, field_id: str, control: str, help_text: str, help_alignment: str = "start", field_class: str = ""
) -> str:
    return (
        f'<div class="tax-field {field_class}"><div class="tax-field-heading"><label for="{field_id}">{label}</label>'
        f'<details class="field-help field-help-{help_alignment}"><summary aria-label="Help for {label}">?</summary><p>{help_text}</p></details>'
        f"</div>{control}</div>"
    )
