"""Local browser dashboard for reviewing and generating investment reports."""

from __future__ import annotations

import html
import json
import webbrowser
from collections.abc import Callable
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from .models import NormalizedReport, ReportError, totals
from .dashboard_selection import DashboardSelection, selection_from_form
from .dashboard_data import DashboardData, load_dashboard_data
from .finder import choose_folder_in_finder, picker_start_folder
from .guidance_mapping import GuidanceResponse, MappedRate, TaxRateMapping, map_gain_rates
from .guidance_modal import render_guidance_modal
from .payment_websites import payment_website
from .guidance_providers import PROVIDER_OPTIONS, provider_label
from .guidance_review import GuidanceReviewService
from .service import generate_report
from .settings import SENSITIVE_CONFIG_KEYS, available_report_years, create_realized_gains_skeleton, editable_config, ensure_config_defaults, realized_gains_root, save_editable_config, save_realized_gains_root, save_tax_input_defaults
from .tax_estimate import FILING_STATUSES, TaxAssumptions, TaxFormula, US_STATES, assumptions_from_form, build_tax_formula, estimate_taxes, state_name

RecordsRootSaver = Callable[[Path], Path | None]
FinderFolderChooser = Callable[[Path | None], Path | None]
RecordsRootProvider = Callable[[], Path | None]
RecordsRootSkeletonCreator = Callable[[Path, int], Path]


def _currency(value: Decimal) -> str:
    prefix = "−" if value < 0 else ""
    return f"{prefix}${abs(value):,.2f}"


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


LOCAL_SETTINGS_LABELS = {
    "realized_gains_root": "Realized gains root",
    "ai_provider": "Default AI provider",
    "openai_api_key": "OpenAI API key",
    "openai_model": "OpenAI model",
    "gemini_api_key": "Google Gemini API key",
    "gemini_model": "Gemini model",
    "openrouter_api_key": "OpenRouter API key",
    "openrouter_model": "OpenRouter model",
    "filing_status": "Default filing status",
    "num_dependents": "Default number of dependents",
    "state_residence": "Default state residence",
    "other_ordinary_taxable_income": "Default other ordinary taxable income ($)",
}


def _render_config_control(key: str, label: str, stored: object) -> str:
    """Render one key-safe local setting control with supported-choice dropdowns."""
    if key in SENSITIVE_CONFIG_KEYS:
        detail = "Configured — leave blank to keep it" if stored else "Not configured"
        return f'<label>{label}<input type="password" name="{key}" autocomplete="off" placeholder="{detail}"><small>{detail}</small></label>'
    options_by_key = {
        "ai_provider": PROVIDER_OPTIONS,
        "filing_status": FILING_STATUSES,
        "state_residence": US_STATES,
    }
    options = options_by_key.get(key)
    if options:
        rendered_options = "".join(
            f'<option value="{_escape(value)}" {"selected" if value == stored else ""}>{_escape(name)}</option>'
            for value, name in options
        )
        return f'<label>{label}<select name="{key}">{rendered_options}</select></label>'
    return f'<label>{label}<input name="{key}" value="{_escape(stored)}"></label>'


def _render_config_modal(values: dict[str, object]) -> str:
    """Render the dashboard's local-only configuration dialog."""
    controls = [_render_config_control(key, label, values.get(key, "")) for key, label in LOCAL_SETTINGS_LABELS.items()]
    return f'''<style>
  .local-settings-dialog {{ width:min(760px,94vw); max-height:90vh; padding:0; border:0; border-radius:14px; color:#102a43; box-shadow:0 24px 70px #102a4355 }} .local-settings-dialog::backdrop {{ background:#102a4388 }} .local-settings-note {{ margin:18px 22px 0; color:#627d98 }} .local-settings-form {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin:18px 22px 22px; padding:0; border:0; box-shadow:none }} .local-settings-form label {{ display:grid; gap:5px; color:#627d98; font-size:12px; font-weight:700 }} .local-settings-form input,.local-settings-form select {{ min-height:38px; padding:8px; border:1px solid #b9c8d6; border-radius:7px; font:inherit }} .local-settings-form small {{ font-weight:400 }} .local-settings-actions {{ grid-column:1/-1; display:flex; align-items:center; justify-content:space-between; gap:12px }} .local-settings-actions p {{ margin:0; color:#627d98 }} @media(max-width:640px) {{ .local-settings-form {{ grid-template-columns:1fr }} }}
</style><button id="open-local-settings" class="secondary-action" type="button">Local settings</button>
<dialog id="local-settings-dialog" class="local-settings-dialog">
  <div class="dialog-heading"><div><h2>Local settings</h2><p>Saved only in config.local.json on this Mac.</p></div><button id="close-local-settings" type="button" aria-label="Close">×</button></div>
  <p class="local-settings-note">Missing settings are filled from config.example.json. API keys remain hidden; leave a key blank to keep it.</p>
  <form id="local-settings-form" class="local-settings-form">{''.join(controls)}<div class="local-settings-actions"><p id="local-settings-status" role="status"></p><button type="submit">Save local settings</button></div></form>
</dialog>
<script>(() => {{
  const button = document.getElementById("open-local-settings"), dialog = document.getElementById("local-settings-dialog"), closeButton = document.getElementById("close-local-settings"), form = document.getElementById("local-settings-form"), status = document.getElementById("local-settings-status");
  if (!button || !dialog || !closeButton || !form || !status) return;
  button.addEventListener("click", () => {{ status.textContent = ""; dialog.showModal(); }});
  closeButton.addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (event) => {{
    event.preventDefault(); status.textContent = "Saving local settings…";
    try {{
      const response = await fetch("/settings", {{ method: "POST", headers: {{ Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" }}, body: new URLSearchParams(new FormData(form)) }});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not save local settings.");
      status.textContent = payload.message || "Local settings saved.";
      form.querySelectorAll('input[type="password"]').forEach((input) => {{ input.value = ""; }});
    }} catch (error) {{ status.textContent = error.message; }}
  }});
}})();</script>'''


def _security_groups(report: NormalizedReport) -> list[tuple[str, list]]:
    """Group individual lots by symbol for the expandable dashboard view."""
    grouped: dict[str, list] = {}
    for lot in report.lots:
        grouped.setdefault(lot.symbol, []).append(lot)
    return sorted(grouped.items(), key=lambda item: totals(item[1])["total_realized_gain_loss_usd"], reverse=True)


def _metric(label: str, value: Decimal) -> str:
    tone = "loss" if value < 0 else "gain"
    return f'<article class="metric"><p>{_escape(label)}</p><strong class="{tone}">{_currency(value)}</strong></article>'


def _render_security_group(symbol: str, lots: list) -> str:
    """Render a security summary with an on-demand table of its realized lots."""
    values = totals(lots)
    total = values["total_realized_gain_loss_usd"]
    lot_rows = "".join(
        f"<tr><td>{_escape(lot.account)}</td><td>{lot.acquired_date:%Y-%m-%d}</td><td>{lot.sale_date:%Y-%m-%d}</td><td>{lot.quantity:,}</td><td>{_currency(lot.proceeds_usd)}</td><td>{_currency(lot.cost_basis_usd)}</td><td>{_escape(lot.tax_term)}</td><td class=\"{'loss' if lot.total_realized_gain_loss_usd < 0 else 'gain'}\">{_currency(lot.total_realized_gain_loss_usd)}</td></tr>"
        for lot in lots
    )
    return f'''<details class="security-group"><summary><span><b>{_escape(symbol)}</b><small>{_escape(lots[0].description)}</small></span><span>{len(lots):,}</span><span>{_currency(values["short_term_gain_loss_usd"])}</span><span>{_currency(values["long_term_gain_loss_usd"])}</span><span class="{'loss' if total < 0 else 'gain'}">{_currency(total)}</span></summary><div class="lot-detail"><h3>{_escape(symbol)} realized lots</h3><div class="table-wrap"><table><thead><tr><th>Account</th><th>Acquired</th><th>Sold</th><th>Quantity</th><th>Proceeds</th><th>Cost basis</th><th>Tax term</th><th>Realized G/L</th></tr></thead><tbody>{lot_rows}</tbody></table></div></div></details>'''


def _render_tax_section(
    report: NormalizedReport,
    selection: DashboardSelection,
    assumptions: TaxAssumptions,
    guidance_response: GuidanceResponse | None = None,
    mapping: TaxRateMapping | None = None,
    guidance_path: Path | None = None,
) -> str:
    """Render household inputs and rates mapped from AI bracket guidance."""
    estimate = estimate_taxes(report, assumptions, guidance_response)
    values = totals(report.lots)
    short_term_gain = max(values["short_term_gain_loss_usd"], Decimal("0"))
    long_term_gain = max(values["long_term_gain_loss_usd"], Decimal("0"))
    state_options = "".join(f'<option value="{code}" {"selected" if code == assumptions.state_code else ""}>{_escape(name)}</option>' for code, name in US_STATES)
    selected_state = state_name(assumptions.state_code)
    state_requirement = "" if assumptions.state_code else '<p id="state-guidance-note" class="state-guidance-note">Select your state of residence first to activate rate guidance.</p>'
    effective_mapping = mapping
    if guidance_response is not None:
        effective_mapping = map_gain_rates(
            guidance_response,
            assumptions.other_ordinary_taxable_income,
            short_term_gain,
            long_term_gain,
        )
    formula = build_tax_formula(
        guidance_response,
        assumptions.other_ordinary_taxable_income,
        short_term_gain,
        long_term_gain,
    ) if guidance_response is not None else None
    federal_payment = payment_website("US")
    state_payment_website = payment_website(assumptions.state_code)
    federal_payment_button = f'<a class="pay-button" href="{_escape(federal_payment.url)}" target="_blank" rel="noopener">Pay federal estimated tax</a>' if federal_payment else ""
    state_payment = f'<a class="pay-button secondary" href="{_escape(state_payment_website.url)}" target="_blank" rel="noopener">Pay {selected_state} estimated tax</a>' if effective_mapping and estimate.state > 0 and state_payment_website and selected_state else ""
    saved_note = f'<p class="tax-note">AI response saved locally: {_escape(guidance_path)}</p>' if guidance_path else ""
    rate_cards = _render_rate_cards(
        effective_mapping,
        assumptions.other_ordinary_taxable_income,
        short_term_gain,
        long_term_gain,
        estimate,
        formula,
    )
    formula_button = _render_formula_button(formula)
    formula_summary = f'<div class="tax-formula-summary">{formula_button}</div>' if formula_button else ""
    guidance_modal = render_guidance_modal(guidance_path is not None)
    settings_modal = _render_config_modal(editable_config())
    return f'''<style>
    .tax-formula-summary {{ display:grid; grid-template-columns:repeat(3,1fr); padding:12px 18px; border-top:1px solid #d9e2ec; background:#fff }}
    .tax-formula-summary .formula-action {{ grid-column:1/-1; justify-self:center }} .tax-formula-summary .formula-action button {{ background:#526d82 }}
    .guidance-rate-table input,.guidance-response-card .deduction input {{ width:100%; min-width:0; min-height:34px; padding:6px; font-size:12px }}
    .guidance-breakdown .add-bracket {{ width:100%; min-height:32px; margin-top:6px; padding:5px; background:#526d82; font-size:12px }} .guidance-rate-table .remove-bracket {{ min-height:32px; padding:5px 7px; background:#9b3a32; font-size:11px }}
    .guidance-response-card .deduction {{ display:grid; gap:6px }}
    .tax-workflow-actions {{ display:grid; grid-template-columns:auto auto minmax(0,1fr); gap:10px; align-items:end; padding:16px 18px; border-top:1px solid #d9e2ec; background:#f8fafc }}
    .tax-workflow-actions .guidance-form {{ grid-column:1/-1; display:flex; align-items:end; gap:10px; padding:0; border:0; border-radius:0; background:transparent; box-shadow:none }}
    .tax-workflow-actions .guidance-provider {{ width:min(300px,100%) }} .tax-workflow-actions .guidance-form button {{ white-space:nowrap }}
    .tax-workflow-actions #switch-guidance-button {{ grid-column:1; margin:0 }} .tax-workflow-actions #open-local-settings {{ grid-column:2; justify-self:start; margin:0 }} .tax-workflow-actions #guidance-profile-note {{ grid-column:1/-1; margin:0 }}
    @media(max-width:800px) {{ .tax-formula-summary {{ grid-template-columns:1fr }} .tax-formula-summary .formula-action {{ grid-column:1 }} .tax-formula-summary .formula-action button {{ width:100% }} .tax-workflow-actions {{ grid-template-columns:1fr }} .tax-workflow-actions .guidance-form {{ grid-column:1; display:grid; grid-template-columns:1fr }} .tax-workflow-actions #switch-guidance-button,.tax-workflow-actions #open-local-settings {{ grid-column:1; width:100% }} }}
    </style><section class="panel tax-panel">
    <div class="panel-heading"><h2>Estimated Tax</h2><span>Planning estimate — not tax advice · No liability assumed</span></div>
    <form method="get" action="/dashboard" class="tax-form"><input type="hidden" name="year" value="{selection.year}"><input type="hidden" name="source" value="{_escape(selection.source_dir)}"><input type="hidden" name="output" value="{_escape(selection.output_dir)}"><label>State residence<select id="state-residence" name="state">{state_options}</select></label><label>Filing status<select id="filing-status" name="filing_status">{_filing_options(assumptions)}</select></label><label>Number of dependents<input id="dependent-count" name="num_dependents" type="number" min="0" max="99" step="1" value="{assumptions.num_dependents}"></label><label>Other ordinary taxable income ($)<input id="ordinary-income" name="other_ordinary_taxable_income" type="number" min="0" step="1" value="{assumptions.other_ordinary_taxable_income:g}"></label><button type="submit">Update estimate</button></form>
    {rate_cards}<div class="tax-results"><article><p>Federal estimate</p><strong>{_currency(estimate.federal)}</strong></article><article><p>State estimate{f" · {assumptions.state_code}" if assumptions.state_code else ""}</p><strong>{_currency(estimate.state)}</strong></article><article><p>Estimated total tax</p><strong>{_currency(estimate.total)}</strong></article></div>{formula_summary}{state_requirement}
    <div class="tax-workflow-actions"><form id="guidance-form" class="guidance-form"><input type="hidden" name="year" value="{selection.year}"><input type="hidden" name="source" value="{_escape(selection.source_dir)}"><input type="hidden" name="output" value="{_escape(selection.output_dir)}"><input id="guidance-state" type="hidden" name="state" value="{assumptions.state_code}"><input id="guidance-filing-status" type="hidden" name="filing_status" value="{_escape(assumptions.filing_status)}"><input id="guidance-dependent-count" type="hidden" name="num_dependents" value="{assumptions.num_dependents}"><input id="guidance-ordinary-income" type="hidden" name="other_ordinary_taxable_income" value="{assumptions.other_ordinary_taxable_income:g}"><label class="guidance-provider">AI provider<select id="ai-provider" name="ai_provider">{_provider_options(assumptions)}</select></label><button id="guidance-button" type="button" {'disabled' if not assumptions.state_code else ''}>Get {provider_label(assumptions.ai_provider)} rate guidance</button></form>{guidance_modal}{settings_modal}</div>
    {saved_note}<div class="tax-actions">{federal_payment_button}{state_payment}</div><p class="tax-note">Tax is calculated incrementally from the approved response's bracket schedules. Federal short-term gains are treated as ordinary income. This planning estimate excludes deductions, credits, surtaxes, carryovers, and other tax-specific adjustments.</p></section>'''


def _render_rate_cards(
    mapping: TaxRateMapping | None,
    ordinary_income: Decimal,
    short_term_gain: Decimal,
    long_term_gain: Decimal,
    estimate,
    formula: TaxFormula | None,
) -> str:
    if mapping is None:
        return '<div class="mapped-rates"><article><p>Mapped tax rates</p><strong>Run rate guidance</strong><small>Enter other ordinary taxable income, select a state, and request guidance to map applicable bracket rates.</small></article></div>'
    ordinary_end = formula.federal_short_term.closing_income if formula else ordinary_income + short_term_gain
    long_term_end = formula.federal_long_term.closing_income if formula else ordinary_end + long_term_gain
    state_end = formula.state.closing_income if formula else ordinary_end + long_term_gain
    cards = (
        _rate_card("Federal ordinary / short-term rate", mapping.federal_short_term, ordinary_end, estimate.federal_short_term),
        _rate_card("Federal long-term rate", mapping.federal_long_term, long_term_end, estimate.federal_long_term),
        _rate_card("State tax rate", mapping.state, state_end, estimate.state),
    )
    return f'<div class="mapped-rates">{"".join(cards)}</div>'


def _rate_card(label: str, mapped_rate: MappedRate, taxable_income: Decimal, tax_amount: Decimal) -> str:
    bracket = f" through {_currency(mapped_rate.bracket_upper_bound)}" if mapped_rate.bracket_upper_bound is not None else " in the top reported bracket"
    return f'<article><p>{_escape(label)}</p><strong>{mapped_rate.rate * 100:g}%</strong><small>Highest bracket reached at taxable income of {_currency(taxable_income)}{bracket}.</small><small>Tax from this type: {_currency(tax_amount)}</small></article>'


def _render_formula_button(formula: TaxFormula | None) -> str:
    """Render a user-triggered view of the exact selected-bracket calculations."""
    if formula is None:
        return ""
    rows = "".join(_formula_row(line, formula) for line in (formula.federal_short_term, formula.federal_long_term, formula.state))
    return f'''<div class="formula-action"><button id="show-tax-formula" type="button">See exact formula</button></div>
    <dialog id="tax-formula-dialog" class="tax-formula-dialog"><div class="dialog-heading"><div><h2>Exact tax formula</h2><p>The selected response's standard deduction is applied to other ordinary income plus short-term gain/loss first. Each tax then adds only the applicable gain portions by bracket, from the highest rate down.</p></div><button id="close-tax-formula" type="button" aria-label="Close">×</button></div><div class="formula-note">Federal short-term and state bracket expressions use their full taxable-income totals, so their bracket amounts add to the total shown. The tax amount remains the estimated incremental tax from investment gains. For long-term gains, any standard deduction left after ordinary and short-term income reduces long-term gain; otherwise the taxable long-term amount is the full long-term gain.</div><div class="table-wrap"><table><thead><tr><th>Tax type</th><th>Total taxable income</th><th>Applicable bracket formula</th><th>Tax amount</th></tr></thead><tbody>{rows}</tbody></table></div></dialog>
    <script>(()=>{{const open=document.getElementById("show-tax-formula"),dialog=document.getElementById("tax-formula-dialog"),close=document.getElementById("close-tax-formula");if(open&&dialog&&close){{open.addEventListener("click",()=>dialog.showModal());close.addEventListener("click",()=>dialog.close());}}}})();</script>'''


def _formula_row(line, formula) -> str:
    if line.label == "Federal long-term":
        taxable_income = (
            f"max({_currency(formula.long_term_gain)} long-term gain − "
            f"{_currency(formula.remaining_standard_deduction)} remaining standard deduction, $0) "
            f"= {_currency(line.closing_income)}"
        )
        if formula.remaining_standard_deduction == Decimal("0"):
            taxable_income = f"{_currency(formula.long_term_gain)} long-term gain = {_currency(line.closing_income)}"
    elif line.label == "State":
        taxable_income = (
            f"{_currency(formula.other_ordinary_income)} other ordinary income + "
            f"{_currency(formula.short_term_gain)} short-term gain + "
            f"{_currency(formula.long_term_gain)} long-term gain − "
            f"{_currency(formula.standard_deduction)} standard deduction = {_currency(line.closing_income)}"
        )
    else:
        taxable_income = (
            f"max({_currency(formula.other_ordinary_income)} other ordinary income + "
            f"{_currency(formula.short_term_gain)} short-term gain − "
            f"{_currency(formula.standard_deduction)} standard deduction, $0)"
        )
        taxable_income += f" = {_currency(line.closing_income)}"
    components = line.total_components if line.label in {"Federal ordinary / short-term", "State"} else line.components
    formula = " + ".join(
        f"({_currency(component.taxable_amount)} × {component.rate * 100:g}%)"
        for component in components
    ) or "$0.00"
    return f"<tr><td>{_escape(line.label)}</td><td>{_escape(taxable_income)}</td><td>{_escape(formula)}</td><td>{_currency(line.tax_amount)}</td></tr>"


def _apply_saved_guidance(
    selection: DashboardSelection,
    assumptions: TaxAssumptions,
    guidance_reviews: GuidanceReviewService,
) -> tuple[TaxAssumptions, TaxRateMapping | None, GuidanceResponse | None, Path | None]:
    """Map a matching saved response, without contacting an AI provider."""
    try:
        applied = guidance_reviews.load_selected(selection.output_dir, selection.year, assumptions)
    except ReportError:
        return assumptions, None, None, None
    if applied is None:
        return assumptions, None, None, None
    return applied.assumptions, applied.mapping, applied.response, applied.path


def _filing_options(assumptions: TaxAssumptions) -> str:
    return "".join(f'<option value="{code}" {"selected" if code == assumptions.filing_status else ""}>{_escape(label)}</option>' for code, label in FILING_STATUSES)


def _provider_options(assumptions: TaxAssumptions) -> str:
    return "".join(f'<option value="{code}" {"selected" if code == assumptions.ai_provider else ""}>{_escape(label)}</option>' for code, label in PROVIDER_OPTIONS)


def _render_loading_dashboard(selection: DashboardSelection) -> str:
    """Render instantly while the browser requests the potentially slow data view."""
    query_values: dict[str, str | int | Path] = {
        "source": selection.source_dir,
        "output": selection.output_dir,
    }
    if selection.year is not None:
        query_values["year"] = selection.year
    query = urlencode(query_values)
    data_url = f"/dashboard?{query}"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Loading · Capital Gain Estimate Tax Calculator</title><style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#f4f7fa; color:#102a43; font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif }}
    main {{ max-width:520px; margin:24px; padding:32px; text-align:center; background:white; border:1px solid #d9e2ec; border-radius:12px; box-shadow:0 1px 2px #102a4310 }}
    .spinner {{ width:32px; height:32px; margin:0 auto 18px; border:4px solid #d9e2ec; border-top-color:#1f5f8b; border-radius:50%; animation:spin .8s linear infinite }} @keyframes spin {{ to {{ transform:rotate(360deg) }} }} h1 {{ margin:0; font-size:24px }} p {{ color:#627d98 }}
    </style></head><body><main><div class="spinner" aria-hidden="true"></div><h1>Loading your investment data</h1><p>Reading the selected brokerage exports and calculating your dashboard. This can take a moment for larger files.</p></main><script>fetch("{data_url}").then(response => response.text()).then(page => {{ document.open(); document.write(page); document.close(); }}).catch(() => {{ document.querySelector("p").textContent = "We couldn’t load the data. Check the source folder and refresh this page."; }});</script></body></html>'''


def _render_terms() -> str:
    """Render the local app's concise terms of service."""
    return _render_terms_base().replace(
        '</p><h2>Third-party services</h2>',
        '<p>DC Technology Consulting assumes no liability or responsibility for your use of the calculator or for any action taken or not taken based on its output.</p><h2>Third-party services</h2>',
        1,
    )


def _render_terms_base() -> str:
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Terms of Service · Capital Gain Estimate Tax Calculator</title><style>
    :root { color-scheme:light; --ink:#102a43; --muted:#627d98; --paper:#f4f7fa; --line:#d9e2ec; --navy:#15324b; --blue:#1f5f8b; } * { box-sizing:border-box } body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif } header { background:var(--navy); color:white; padding:32px max(24px,calc((100vw - 800px)/2)) } header p { margin:4px 0 0; color:#c7d7e6 } h1 { margin:0; font-size:28px } main { max-width:800px; margin:28px auto 48px; padding:28px; background:white; border:1px solid var(--line); border-radius:12px; box-shadow:0 1px 2px #102a4310 } h2 { margin:28px 0 8px; font-size:19px } h2:first-of-type { margin-top:24px } p { margin:8px 0 } .muted { color:var(--muted) } a { color:var(--blue); font-weight:700 } footer { max-width:800px; margin:-28px auto 36px; color:var(--muted); text-align:center; font-size:13px }
    </style></head><body><header><h1>Terms of Service</h1><p>Capital Gain Estimate Tax Calculator</p></header><main><p class="muted">Last updated: August 31, 2026</p><p>Capital Gain Estimate Tax Calculator is developed by <strong>DC Technology Consulting</strong> and is provided for open-source, free use.</p><h2>Permitted use</h2><p>You may use, copy, modify, and share this software at no cost. Keep this notice with material redistributions.</p><h2>Important limitations</h2><p>This software is an informational tool. It is not tax, legal, accounting, or investment advice. You are responsible for reviewing all imported data, calculations, tax rates, generated reports, and any payment decisions with qualified professionals where appropriate.</p><p>Estimated-tax guidance and payment-site links are provided for convenience only. Confirm current rules, amounts, deadlines, and official payment destinations before acting.</p><h2>No warranty and limitation of liability</h2><p>The software is provided “as is” and “as available,” without warranties of any kind. To the maximum extent permitted by law, DC Technology Consulting is not liable for losses, damages, taxes, penalties, interest, or other claims resulting from use of the software, its reports, external links, or generated guidance.</p><h2>Third-party services</h2><p>Optional features may communicate with third-party services, including OpenAI and government payment websites. Their terms, privacy practices, availability, and charges apply.</p><h2>Changes</h2><p>These terms may be updated with future releases. Continued use after an update means you accept the revised terms.</p><p><a href="/">Return to dashboard</a></p></main><footer>Developed by DC Technology Consulting · Open-source, free use</footer></body></html>'''


def _render_dashboard(
    selection: DashboardSelection | None,
    assumptions: TaxAssumptions | None = None,
    notice: str = "",
    error: str = "",
    report_ready: bool = False,
    guidance_response: GuidanceResponse | None = None,
    mapping: TaxRateMapping | None = None,
    guidance_path: Path | None = None,
    dashboard_data: DashboardData | None = None,
) -> str:
    root = realized_gains_root()
    years = set(available_report_years(root))
    summary = ""
    if selection and not error:
        try:
            data = dashboard_data or load_dashboard_data(selection)
            selection = data.selection
            report = data.report
            years.update(report.available_sale_years)
            values = totals(report.lots)
            metrics = "".join((_metric("Total realized gain/loss", values["total_realized_gain_loss_usd"]), _metric("Short-term", values["short_term_gain_loss_usd"]), _metric("Long-term", values["long_term_gain_loss_usd"]), _metric("Proceeds", values["proceeds_usd"])))
            source_rows = "".join(f"<tr><td>{_escape(item.source_name)}</td><td>{item.included_rows:,}</td><td>{_escape(item.earliest_sale)}</td><td>{_escape(item.latest_sale)}</td></tr>" for item in report.sources)
            security_groups = "".join(_render_security_group(symbol, lots) for symbol, lots in _security_groups(report))
            tax_section = _render_tax_section(report, selection, assumptions or TaxAssumptions(), guidance_response, mapping, guidance_path)
            summary = f'''<section class="metrics">{metrics}</section>{tax_section}
            <section class="panel"><div class="panel-heading"><h2>Security summary</h2><span>{len(report.lots):,} realized lots · select a security to view its lots</span></div><div class="security-head"><span>Security</span><span>Lots</span><span>Short-term</span><span>Long-term</span><span>Total G/L</span></div>{security_groups}</section>
            <section class="panel sources"><h2>Included sources</h2><table><thead><tr><th>Source</th><th>Records</th><th>Earliest sale</th><th>Latest sale</th></tr></thead><tbody>{source_rows}</tbody></table></section>'''
        except (ReportError, OSError) as exc:
            error = str(exc)
    selected_year = selection.year if selection and selection.year is not None else ""
    source = str(selection.source_dir) if selection else (str(root) if root else "")
    output = str(selection.output_dir) if selection else ""
    sorted_years = sorted(years)
    auto_selected = "selected" if not selected_year else ""
    options = f'<option value="" {auto_selected}>Auto-detect</option>'
    options += "".join(
        f'<option value="{year}" {"selected" if year == selected_year else ""}>{year}</option>'
        for year in sorted_years
    )
    if selected_year and selected_year not in years:
        options += f'<option selected value="{selected_year}">{selected_year}</option>'
    message = f'<p class="notice">{_escape(notice)}</p>' if notice else ""
    download = '<p><a class="download" href="/download">Download generated workbook</a></p>' if report_ready else ""
    failure = f'<p class="error">{_escape(error)}</p>' if error else ""
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Capital Gain Estimate Tax Calculator</title><style>
    :root {{ color-scheme: light; --ink:#102a43; --muted:#627d98; --paper:#f4f7fa; --line:#d9e2ec; --navy:#15324b; --blue:#1f5f8b; --gain:#087f5b; --loss:#b42318; }}
    .tax-actions {{ display:flex; gap:10px; padding:14px 18px 0 }} .pay-button {{ display:inline-block; padding:9px 12px; border-radius:7px; background:#087f5b; color:white; font-weight:700; text-decoration:none }} .pay-button.secondary {{ background:#1f5f8b }} .state-guidance-note {{ margin:14px 18px 0; padding:12px 14px; border-left:4px solid #d97706; border-radius:6px; background:#fff7df; color:#8a4b00; font-weight:700 }} .guidance-form {{ display:block; padding:14px 18px 0; border:0; border-radius:0; box-shadow:none }} .guidance-form button:disabled {{ background:#9aaabd; color:#edf2f7; cursor:not-allowed; opacity:1 }} .guidance {{ margin:14px 18px 0; border:1px solid var(--line); border-radius:8px; background:#f8fafc }} .guidance summary {{ padding:12px; cursor:pointer; color:var(--blue); font-weight:700 }} .guidance pre {{ margin:0; padding:0 12px 12px; white-space:pre-wrap; font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif }} .app-footer {{ max-width:1200px; margin:-28px auto 28px; padding:0 24px; color:var(--muted); font-size:13px; text-align:center }} .app-footer a {{ color:var(--blue); font-weight:700 }}
    .secondary-action {{ margin:12px 18px 0; background:#526d82 }} .guidance-dialog {{ width:min(1160px,96vw); max-height:92vh; padding:0; border:0; border-radius:14px; color:var(--ink); box-shadow:0 24px 70px #102a4355 }} .guidance-dialog::backdrop {{ background:#102a4388 }} .dialog-heading {{ display:flex; justify-content:space-between; gap:20px; padding:20px 22px; border-bottom:1px solid var(--line) }} .dialog-heading h2,.dialog-heading p {{ margin:0 }} .dialog-heading p {{ color:var(--muted) }} #close-guidance-dialog {{ min-width:40px; font-size:24px; background:#526d82 }} .guidance-progress {{ margin:18px 22px; padding:13px 15px; border-radius:8px; background:#e7f3ff; color:#174d72; font-weight:700 }} .guidance-progress.processing {{ border-left:5px solid #1f5f8b }} .guidance-response-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; padding:0 22px 18px }} .guidance-response-card {{ min-width:0; padding:15px; border:1px solid var(--line); border-radius:10px; background:white }} .guidance-response-card.placeholder {{ display:grid; min-height:260px; place-content:center; color:var(--muted); text-align:center; background:#f8fafc; border-style:dashed }} .guidance-response-card h3 {{ margin:0 0 10px }} .guidance-rate-table th,.guidance-rate-table td {{ padding:7px 6px; white-space:normal; font-size:12px }} .guidance-response-card .deduction {{ padding:10px; border-radius:7px; background:#f0f7f4; font-weight:700 }} .response-actions {{ display:flex; gap:8px; margin-top:12px }} .response-actions button {{ flex:1 }} .response-actions .discard-response {{ background:#9b3a32 }} .guidance-round-message {{ margin:0; padding:0 22px 22px; color:var(--muted) }} @media(max-width:900px) {{ .guidance-response-grid {{ grid-template-columns:1fr }} }}
    * {{ box-sizing:border-box }} body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif }}
    header {{ background:var(--navy); color:white; padding:32px max(24px,calc((100vw - 1200px)/2)); }} header p {{ margin:4px 0 0; color:#c7d7e6 }} h1 {{ margin:0; font-size:28px }} h2 {{ margin:0; font-size:18px }} main {{ max-width:1200px; margin:24px auto 48px; padding:0 24px }}
    form,.panel,.metric {{ background:white; border:1px solid var(--line); border-radius:12px; box-shadow:0 1px 2px #102a4310 }} form {{ display:grid; grid-template-columns:120px 1fr auto; gap:12px; align-items:end; padding:18px; }} label {{ display:grid; gap:5px; color:var(--muted); font-size:12px; font-weight:600 }} input,select,button {{ min-height:38px; border-radius:7px; border:1px solid #b9c8d6; padding:8px; font:inherit }} button {{ background:var(--blue); color:white; border:0; cursor:pointer; font-weight:700 }} .load-data-form {{ grid-template-columns:140px minmax(0,1fr) auto; padding:16px 18px }} .source-folder-control {{ min-width:0 }} .source-folder-row {{ display:flex; min-width:0; gap:8px }} .source-folder-path {{ display:block; flex:1; min-width:0; min-height:38px; overflow:hidden; padding:8px 10px; border:1px solid #b9c8d6; border-radius:7px; background:#f8fafc; color:var(--ink); font-size:13px; font-weight:500; line-height:20px; text-overflow:ellipsis; white-space:nowrap }} .source-folder-button {{ flex:0 0 auto; min-width:108px; padding-inline:12px; background:#526d82 }} .load-data-button {{ padding-inline:18px }} .source-folder-status {{ margin:0; color:var(--muted); font-size:12px }} .source-folder-status:empty {{ display:none }} .source-folder-status.error {{ color:#b42318 }} .report-actions {{ grid-template-columns:minmax(280px,1fr) auto auto auto; align-items:center }} .report-actions .checkbox {{ display:flex; align-items:center; gap:8px; white-space:nowrap }} .report-actions .checkbox input {{ appearance:auto; min-height:auto; width:18px; height:18px; margin:0; padding:0 }} .metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:20px 0 }} .metric {{ padding:16px }} .metric p,.panel-heading span {{ margin:0; color:var(--muted); font-size:13px }} .metric strong {{ display:block; margin-top:6px; font-size:24px }} .gain {{ color:var(--gain) }} .loss {{ color:var(--loss) }} .panel {{ margin-top:18px; overflow:hidden }} .panel-heading {{ display:flex; justify-content:space-between; align-items:center; padding:16px 18px; border-bottom:1px solid var(--line) }} .tax-form {{ grid-template-columns:repeat(4,minmax(145px,1fr)) auto; border:0; border-radius:0; box-shadow:none; border-bottom:1px solid var(--line) }} .mapped-rates {{ display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--line) }} .mapped-rates article {{ padding:16px 18px; background:#f8fafc }} .mapped-rates p,.mapped-rates small {{ display:block; margin:0; color:var(--muted); font-size:13px }} .mapped-rates strong {{ display:block; margin:5px 0; font-size:22px }} .tax-results {{ display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--line) }} .tax-results article {{ margin:0; padding:16px 18px; background:white }} .tax-results p,.tax-note {{ margin:0; color:var(--muted); font-size:13px }} .tax-results strong {{ display:block; margin-top:5px; font-size:22px }} .tax-note {{ padding:14px 18px }} .security-head,.security-group summary {{ display:grid; grid-template-columns:minmax(250px,1fr) 80px 130px 130px 130px; gap:12px; align-items:center; padding:12px 18px }} .security-head {{ color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.03em; background:#f8fafc }} .security-group {{ display:block; border-top:1px solid var(--line) }} .security-group summary {{ cursor:pointer; list-style:none }} .security-group summary::-webkit-details-marker {{ display:none }} .security-group summary:hover {{ background:#f8fafc }} .security-group summary span:first-child {{ display:grid; gap:2px }} .security-group summary small {{ color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap }} .lot-detail {{ padding:14px 18px 18px; background:#f8fafc }} .lot-detail h3 {{ margin:0 0 10px; font-size:14px }} .sources h2 {{ padding:16px 18px 0 }} table {{ border-collapse:collapse; width:100% }} th,td {{ padding:11px 14px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap }} th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.03em }} td:last-child {{ font-weight:600 }} .table-wrap {{ overflow:auto }} .notice,.error {{ padding:12px 14px; border-radius:8px; background:#dff7ed; color:#065f46 }} .error {{ background:#fee4e2; color:#8a1c13 }} .actions {{ display:flex; gap:10px; align-items:center }} .download {{ color:var(--blue); font-weight:700 }} @media(max-width:800px) {{ form,.load-data-form,.report-actions,.tax-form {{ grid-template-columns:1fr }} .report-actions .checkbox {{ min-height:38px }} .load-data-button {{ width:100% }} .tax-results,.mapped-rates {{ grid-template-columns:1fr }} .security-head,.security-group summary {{ min-width:720px }} .security-group,.security-head {{ overflow-x:auto }} .metrics {{ grid-template-columns:repeat(2,1fr) }} }} @media(max-width:480px) {{ .source-folder-row {{ flex-direction:column }} .source-folder-button {{ width:100% }} .metrics {{ grid-template-columns:1fr }} main {{ padding:0 14px }} }}
    </style></head><body><header><h1>Capital Gain Estimate Tax Calculator</h1><p>Understand realized gains and explore estimated taxes.</p></header><main>
    <form class="load-data-form" method="get" action="/dashboard" style="align-items:start"><label>Sale year<select id="sale-year" name="year">{options}</select></label><label class="source-folder-control">Source folder<input id="source-folder-value" type="hidden" name="source" value="{_escape(source)}"><span class="source-folder-row"><output id="source-folder-path" class="source-folder-path" title="{_escape(source)}">{_escape(source) if source else "No folder selected"}</output><button id="source-folder" class="source-folder-button" type="submit" formaction="/open-realized-gains-root" formmethod="post" formtarget="finder-result">Choose folder</button></span><span id="source-folder-status" class="source-folder-status" role="status"></span></label><label class="load-data-control"><span aria-hidden="true">&nbsp;</span><button class="load-data-button" type="submit" formaction="/dashboard" formmethod="get">Load data</button></label></form><iframe name="finder-result" hidden></iframe><form id="setup-realized-gains-form" method="post" action="/setup-realized-gains-root" target="finder-result" style="display:none"><input id="setup-realized-gains-parent" name="parent"><input id="setup-realized-gains-year" name="year"></form>{message}{download}{failure}{summary}
    <form class="report-actions" method="post" action="/generate" style="margin-top:18px"><input type="hidden" name="year" value="{_escape(selected_year)}"><input type="hidden" name="source" value="{_escape(source)}"><label>Report folder<input name="output" value="{_escape(output)}" placeholder="…/2026/reports"></label><label class="checkbox"><input name="audit" type="checkbox"> Keep audit files</label><label class="checkbox"><input name="overwrite" type="checkbox" checked> Archive existing report</label><button type="submit">Create Excel report</button></form>
    </main><footer class="app-footer">Developed by DC Technology Consulting · Open-source, free use · <a href="/terms">Terms of Service</a></footer><script>const sourceFolderStatus=document.getElementById("source-folder-status"),sourceFolderValue=document.getElementById("source-folder-value"),sourceFolderPath=document.getElementById("source-folder-path"); window.addEventListener("message",event=>{{if(event.origin!==window.location.origin||event.data?.type!=="finder-result"||!sourceFolderStatus)return; sourceFolderStatus.textContent=event.data.message; sourceFolderStatus.classList.toggle("error",!event.data.ok); if(event.data.source){{if(sourceFolderValue)sourceFolderValue.value=event.data.source;if(sourceFolderPath){{sourceFolderPath.textContent=event.data.source;sourceFolderPath.title=event.data.source;}}}}}});</script><script>(()=>{{const status=document.getElementById("source-folder-status"),setupForm=document.getElementById("setup-realized-gains-form"),parent=document.getElementById("setup-realized-gains-parent"),year=document.getElementById("setup-realized-gains-year"),saleYear=document.getElementById("sale-year");window.addEventListener("message",event=>{{if(event.origin!==window.location.origin||event.data?.type!=="finder-result"||!event.data.setup_parent||!status||!setupForm||!parent||!year)return;const button=document.createElement("button");button.type="button";button.textContent="Set up folders";button.addEventListener("click",()=>{{parent.value=event.data.setup_parent;year.value=saleYear?.value||String(new Date().getFullYear());setupForm.requestSubmit();}});status.replaceChildren(document.createTextNode("Create a standard Realized Gains folder here? "),button);}});}})();</script></body></html>'''


class InvestmentGainWebApp:
    """HTTP application boundary for the local single-user dashboard."""

    def __init__(
        self,
        records_root_saver: RecordsRootSaver = save_realized_gains_root,
        finder_folder_chooser: FinderFolderChooser = choose_folder_in_finder,
        records_root_skeleton_creator: RecordsRootSkeletonCreator = create_realized_gains_skeleton,
        records_root_provider: RecordsRootProvider = realized_gains_root,
    ) -> None:
        ensure_config_defaults()
        self.latest_report: Path | None = None
        self.guidance_reviews = GuidanceReviewService()
        self.records_root_saver = records_root_saver
        self.finder_folder_chooser = finder_folder_chooser
        self.records_root_skeleton_creator = records_root_skeleton_creator
        self.records_root_provider = records_root_provider

    def handler(self):
        application = self

        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                request = urlparse(self.path)
                if request.path == "/download" and application.latest_report and application.latest_report.is_file():
                    payload = application.latest_report.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    self.send_header("Content-Disposition", f'attachment; filename="{application.latest_report.name}"')
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers(); self.wfile.write(payload)
                    return
                if request.path == "/" and not request.query:
                    selection = selection_from_form({})
                    if selection:
                        self._send_html(_render_loading_dashboard(selection))
                        return
                if request.path == "/terms":
                    self._send_html(_render_terms())
                    return
                if request.path not in ("/", "/dashboard"):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                form = parse_qs(request.query)
                save_tax_input_defaults(form)
                selection = selection_from_form(form)
                assumptions = assumptions_from_form(form)
                try:
                    if selection is None:
                        self._send_html(_render_dashboard(None, assumptions))
                    else:
                        dashboard_data = load_dashboard_data(selection)
                        selection = dashboard_data.selection
                        mapped_assumptions, mapping, guidance_response, guidance_path = _apply_saved_guidance(selection, assumptions, application.guidance_reviews)
                        self._send_html(_render_dashboard(selection, mapped_assumptions, guidance_response=guidance_response, mapping=mapping, guidance_path=guidance_path, dashboard_data=dashboard_data))
                except (ReportError, OSError) as exc:
                    self._send_html(_render_dashboard(selection, assumptions, error=str(exc)), HTTPStatus.BAD_REQUEST)

            def do_POST(self) -> None:  # noqa: N802
                if self.path not in ("/generate", "/guidance-saved", "/guidance-query", "/guidance-save", "/open-realized-gains-root", "/setup-realized-gains-root", "/settings"):
                    self.send_error(HTTPStatus.NOT_FOUND); return
                length = int(self.headers.get("Content-Length", "0"))
                form = parse_qs(self.rfile.read(length).decode())
                if self.path == "/open-realized-gains-root":
                    root = None
                    try:
                        source_value = form.get("source", [""])[0].strip()
                        initial_folder = picker_start_folder(source_value, application.records_root_provider())
                        root = application.finder_folder_chooser(initial_folder)
                        if root is None:
                            self._send_finder_result("No folder was selected.", ok=True)
                        else:
                            saved_root = application.records_root_saver(root)
                            self._send_finder_result("Realized gains folder saved.", ok=True, source=saved_root or root)
                    except (ReportError, OSError, ValueError) as exc:
                        self._send_finder_result(str(exc), ok=False, status=HTTPStatus.BAD_REQUEST, setup_parent=root)
                    return
                if self.path == "/settings":
                    try:
                        save_editable_config(form)
                        self._send_json({"message": "Local settings saved."})
                    except OSError as exc:
                        self._send_json({"error": f"Could not save local settings: {exc}"}, HTTPStatus.BAD_REQUEST)
                    return
                if self.path == "/setup-realized-gains-root":
                    try:
                        parent = Path(form.get("parent", [""])[0])
                        year = int(form.get("year", [""])[0])
                        records_root = application.records_root_skeleton_creator(parent, year)
                        source_folder = records_root / str(year) / "source"
                        self._send_finder_result(
                            f"Folders are ready. Put brokerage CSV files in {source_folder}, then select Load data.",
                            ok=True,
                            source=records_root,
                        )
                    except (OSError, ValueError) as exc:
                        self._send_finder_result(str(exc), ok=False, status=HTTPStatus.BAD_REQUEST)
                    return
                save_tax_input_defaults(form)
                selection = selection_from_form(form)
                if selection is None:
                    self._send_html(_render_dashboard(None, error="Choose a valid sale year and source folder."), HTTPStatus.BAD_REQUEST); return
                if self.path == "/guidance-saved":
                    try:
                        assumptions = assumptions_from_form(form)
                        responses = application.guidance_reviews.load_candidates(selection.output_dir, selection.year, assumptions)
                        self._send_json({"responses": responses, "selected_index": 0})
                    except (ReportError, OSError) as exc:
                        self._send_json({"responses": [], "selected_index": 0, "warning": f"Existing saved guidance is incompatible and was not used: {exc}"})
                    return
                if self.path == "/guidance-query":
                    try:
                        attempt = int(form.get("attempt", ["0"])[0])
                        if not 1 <= attempt <= 5:
                            raise ReportError("AI request attempt must be between 1 and 5.")
                        assumptions = assumptions_from_form(form)
                        response = application.guidance_reviews.request_candidate(selection.year, assumptions)
                        self._send_json({"valid": True, "attempt": attempt, "response": response})
                    except (ReportError, OSError) as exc:
                        self._send_json({"valid": False, "error": str(exc)})
                    return
                if self.path == "/guidance-save":
                    try:
                        assumptions = assumptions_from_form(form)
                        raw_responses = json.loads(form.get("responses", ["[]"])[0])
                        if not isinstance(raw_responses, list) or not all(isinstance(item, dict) for item in raw_responses):
                            raise ReportError("The reviewed AI responses were not valid JSON objects.")
                        selected_index = int(form.get("selected_index", ["-1"])[0])
                        paths = application.guidance_reviews.save_candidates(selection.output_dir, selection.year, assumptions, raw_responses, selected_index)
                        self._send_json({"saved": [str(path) for path in paths], "selected": str(paths[selected_index])})
                    except (ReportError, OSError, ValueError, json.JSONDecodeError) as exc:
                        self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    report_path, _ = generate_report(selection.source_dir, selection.year, selection.output_dir, overwrite="overwrite" in form, keep_audit_files="audit" in form)
                    application.latest_report = report_path
                    message = f"Created {report_path.name}. Download it from this browser session."
                    self._send_html(_render_dashboard(selection, notice=message, report_ready=True))
                except (ReportError, OSError) as exc:
                    self._send_html(_render_dashboard(selection, error=str(exc)), HTTPStatus.BAD_REQUEST)

            def _send_html(self, page: str, status: HTTPStatus = HTTPStatus.OK) -> None:
                payload = page.encode("utf-8")
                self.send_response(status); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)

            def _send_json(self, value: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
                payload = json.dumps(value).encode("utf-8")
                self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)

            def _send_finder_result(self, message: str, ok: bool, status: HTTPStatus = HTTPStatus.OK, source: Path | None = None, setup_parent: Path | None = None) -> None:
                result = json.dumps({"type": "finder-result", "message": message, "ok": ok, "source": str(source) if source else None, "setup_parent": str(setup_parent) if setup_parent else None})
                page = f'<!doctype html><script>parent.postMessage({result}, window.location.origin)</script>'
                self._send_html(page, status)

            def log_message(self, *_args: object) -> None:
                return

        return RequestHandler


def run_web_app(host: str = "127.0.0.1", port: int = 8765) -> int:
    """Run the dashboard only on the local computer."""
    server = ThreadingHTTPServer((host, port), InvestmentGainWebApp().handler())
    dashboard_url = f"http://{host}:{port}"
    print(f"Capital Gain Estimate Tax Calculator web app: {dashboard_url}")
    webbrowser.open(dashboard_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
