"""Pure rendering for the report-dependent portion of the dashboard page."""

from __future__ import annotations

from dataclasses import dataclass

from ..dashboard_selection import DashboardSelection
from ..models import NormalizedReport, totals
from .dashboard_details import render_metric, render_security_group, render_sources_section, security_groups


@dataclass(frozen=True)
class DashboardSummaryViewModel:
    """All display inputs required for a loaded-report dashboard summary."""

    report: NormalizedReport
    selection: DashboardSelection
    tax_panel: str


def render_dashboard_summary(view: DashboardSummaryViewModel) -> str:
    """Render report metrics, tax output, security details, and sources only."""
    values = totals(view.report.lots)
    metrics = "".join(
        (
            render_metric("Total realized gain/loss", values["total_realized_gain_loss_usd"]),
            render_metric("Short-term", values["short_term_gain_loss_usd"]),
            render_metric("Long-term", values["long_term_gain_loss_usd"]),
            render_metric("Proceeds", values["proceeds_usd"]),
        )
    )
    security_groups_markup = "".join(
        render_security_group(symbol, lots) for symbol, lots in security_groups(view.report)
    )
    return f"""<section class="metrics">{metrics}</section>{view.tax_panel}
    <section class="panel"><div class="panel-heading"><h2>Security summary</h2><span>{len(view.report.lots):,} realized lots · select a security to view its lots</span></div><div class="security-head"><span>Security</span><span>Lots</span><span>Short-term</span><span>Long-term</span><span>Total G/L</span></div>{security_groups_markup}</section>
    {render_sources_section(view.report, view.selection)}"""
