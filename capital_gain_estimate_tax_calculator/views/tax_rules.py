"""Pure renderer for the typed tax-rule dialog display model."""

from __future__ import annotations

from decimal import Decimal

from ..tax_domain import BracketBand, JurisdictionRuleDisplay, TaxRuleCard, TaxRuleDetail
from ..tax_rules import TaxRuleBundle
from .html import currency, escape, rule_label


def render_tax_rules_modal(rules: TaxRuleBundle) -> str:
    display = rules.display
    federal = _render_jurisdiction("Federal", display.federal, rules.filing_status, "Credits")
    state = _render_jurisdiction(
        rules.state_name or "State", display.state, rules.filing_status, "Credits and dependent benefits"
    )
    return f"""<div class="tax-rules-action"><button id="show-tax-rules" type="button">View tax rules</button></div>
    <dialog id="tax-rules-dialog" class="tax-rules-dialog"><div class="dialog-heading"><div><h2>{rules.year} tax rules</h2><p>{escape(rule_label(rules.filing_status))}</p></div><button id="close-tax-rules" type="button" aria-label="Close">×</button></div><div class="tax-rules-body">{federal}{state}</div></dialog>
    <script>(()=>{{const open=document.getElementById("show-tax-rules"),dialog=document.getElementById("tax-rules-dialog"),close=document.getElementById("close-tax-rules");if(open&&dialog&&close){{open.addEventListener("click",()=>dialog.showModal());close.addEventListener("click",()=>dialog.close());}}}})();</script>"""


def _render_jurisdiction(name: str, display: JurisdictionRuleDisplay, filing_status: str, credit_heading: str) -> str:
    tables = "".join(_render_bracket_table(table.title, table.schedule.bands) for table in display.bracket_tables)
    tables = tables or '<p class="empty-rule">No state income-tax brackets are specified.</p>'
    deduction = _render_standard_deduction(
        display.standard_deduction, display.standard_deduction_details, filing_status
    )
    credits = _render_credit_information(display.credits)
    return f'<section class="jurisdiction-rules"><h3>{escape(name)}</h3><h4>Tax brackets</h4>{tables}<h4>Standard deduction</h4>{deduction}<h4>{credit_heading}</h4><div class="credit-rules">{credits}</div></section>'


def _render_bracket_table(title: str, bands: tuple[BracketBand, ...]) -> str:
    rendered = ""
    lower = Decimal("0")
    for band in bands:
        upper_text = "and above" if band.upper_bound is None else f"to {currency(band.upper_bound)}"
        rendered += f"<tr><td>{escape(f'{currency(lower)} {upper_text}')}</td><td>{escape(band.rate * Decimal('100'))}%</td></tr>"
        if band.upper_bound is not None:
            lower = band.upper_bound
    return f"<section><h4>{escape(title)}</h4><table><thead><tr><th>Taxable income</th><th>Rate</th></tr></thead><tbody>{rendered}</tbody></table></section>"


def _render_standard_deduction(
    deduction: Decimal | None, details: tuple[TaxRuleDetail, ...], filing_status: str
) -> str:
    selected = currency(deduction) if deduction is not None else "Not specified"
    extras = "".join(f"<li><strong>{escape(item.label)}:</strong> {escape(item.value)}</li>" for item in details)
    return f"<p><strong>{escape(rule_label(filing_status))}:</strong> {selected}</p>{f'<ul>{extras}</ul>' if extras else ''}"


def _render_credit_information(cards: tuple[TaxRuleCard, ...]) -> str:
    if not cards:
        return '<p class="empty-rule">No credits are specified.</p>'
    return "".join(
        f'<article class="credit-rule"><h4>{escape(card.title)}</h4><ul>'
        + "".join(f"<li><strong>{escape(item.label)}:</strong> {escape(item.value)}</li>" for item in card.details)
        + "</ul></article>"
        for card in cards
    )
