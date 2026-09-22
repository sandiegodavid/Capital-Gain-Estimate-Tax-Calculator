"""Pure renderers for dashboard metrics, source controls, and lot details."""

from __future__ import annotations

from decimal import Decimal

from ..dashboard_selection import SOURCE_FILE_FIELD, SOURCE_SELECTION_MARKER, DashboardSelection
from ..models import Lot, NormalizedReport, SourceSummary, totals
from ..normalizer import SCHWAB_SCHEMA
from .html import currency, escape


def security_groups(report: NormalizedReport) -> list[tuple[str, list[Lot]]]:
    """Group individual lots by symbol for the expandable dashboard view."""
    grouped: dict[str, list[Lot]] = {}
    for lot in report.lots:
        grouped.setdefault(lot.symbol, []).append(lot)
    return sorted(
        grouped.items(),
        key=lambda item: totals(item[1])["total_realized_gain_loss_usd"],
        reverse=True,
    )


def render_metric(label: str, value: Decimal) -> str:
    tone = "loss" if value < 0 else "gain"
    return f'<article class="metric"><p>{escape(label)}</p><strong class="{tone}">{currency(value)}</strong></article>'


def source_selection_inputs(selection: DashboardSelection) -> str:
    """Preserve an explicit source-file selection across dashboard actions."""
    if selection.included_source_files is None:
        return ""
    selected = "".join(
        f'<input type="hidden" name="{SOURCE_FILE_FIELD}" value="{escape(source_file)}">'
        for source_file in selection.included_source_files
    )
    return f'<input type="hidden" name="{SOURCE_SELECTION_MARKER}" value="1">{selected}'


def render_security_group(symbol: str, lots: list[Lot]) -> str:
    """Render a security summary with an on-demand table of its realized lots."""
    values = totals(lots)
    total = values["total_realized_gain_loss_usd"]
    lot_rows = "".join(_render_lot_row(lot) for lot in lots)
    return f'''<details class="security-group"><summary><span><b>{escape(symbol)}</b><small>{escape(lots[0].description)}</small></span><span>{len(lots):,}</span><span>{currency(values["short_term_gain_loss_usd"])}</span><span>{currency(values["long_term_gain_loss_usd"])}</span><span class="{"loss" if total < 0 else "gain"}">{currency(total)}</span></summary><div class="lot-detail"><h3>{escape(symbol)} realized lots</h3><div class="table-wrap"><table><thead><tr><th>Account / brokerage</th><th>Acquired</th><th>Sold</th><th>Quantity</th><th>Proceeds</th><th>Cost basis</th><th>Tax term</th><th>Realized G/L</th></tr></thead><tbody>{lot_rows}</tbody></table></div></div></details>'''


def render_sources_section(report: NormalizedReport, selection: DashboardSelection) -> str:
    """Render persistent include/exclude controls for each recognized source file."""
    source_rows = "".join(_render_source_row(item, selection) for item in report.sources)
    has_schwab = any(
        item.source_name == SCHWAB_SCHEMA and selection.includes_source(item.source_file) for item in report.sources
    )
    schwab_note = (
        """<aside class="source-note" role="note"><span aria-hidden="true">ℹ</span><div><strong>Charles Schwab source note</strong><p>Schwab exports do not include acquisition dates, so the closed date is shown as the acquisition-date placeholder. The populated long-term or short-term gain/loss column determines the tax term.</p></div></aside>"""
        if has_schwab
        else ""
    )
    return f"""<style>.source-toggle{{display:flex;align-items:center;gap:8px;color:var(--ink);font-size:14px}}.source-toggle input{{appearance:auto;min-height:auto;width:16px;height:16px;margin:0;padding:0;accent-color:var(--gain)}}.sources td small{{display:block;margin:3px 0 0 24px;color:var(--muted);font-size:11px}}.source-note{{display:flex;gap:10px;align-items:flex-start;margin:14px 18px 18px;padding:11px 13px;border:1px solid #bfd7ea;border-radius:8px;background:#f2f8fc;color:#315a78;font-size:13px}}.source-note>span{{font-size:16px;line-height:1.35}}.source-note strong{{display:block;color:var(--ink)}}.source-note p{{margin:2px 0 0;color:var(--muted)}}</style><section id="included-sources" class="panel sources"><div class="panel-heading"><h2>Included sources</h2><span>Use a toggle to include or exclude a source</span></div><table><thead><tr><th>Source</th><th>Records</th><th>Earliest sale</th><th>Latest sale</th></tr></thead><tbody>{source_rows}</tbody></table>{schwab_note}</section>"""


def _render_source_row(item: SourceSummary, selection: DashboardSelection) -> str:
    is_selected = selection.includes_source(item.source_file)
    return (
        f'<tr><td><label class="source-toggle"><input type="checkbox" data-source-toggle '
        f'value="{escape(item.source_file)}" {"checked" if is_selected else ""}> '
        f"<span>{escape(item.source_name)}</span></label><small>{escape(item.source_file)}</small></td>"
        f"<td>{item.included_rows:,}</td><td>{escape(item.earliest_sale)}</td><td>{escape(item.latest_sale)}</td></tr>"
    )


def _render_lot_row(lot: Lot) -> str:
    account_or_brokerage = lot.account or lot.source_name
    gain_loss = lot.total_realized_gain_loss_usd
    gain_loss_class = "loss" if gain_loss < 0 else "gain"
    return (
        f"<tr><td>{escape(account_or_brokerage)}</td><td>{lot.acquired_date:%Y-%m-%d}</td>"
        f"<td>{lot.sale_date:%Y-%m-%d}</td><td>{lot.quantity:,}</td>"
        f"<td>{currency(lot.proceeds_usd)}</td><td>{currency(lot.cost_basis_usd)}</td>"
        f'<td>{escape(lot.tax_term)}</td><td class="{gain_loss_class}">{currency(gain_loss)}</td></tr>'
    )
