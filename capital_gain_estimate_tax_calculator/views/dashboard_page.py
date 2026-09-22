"""Pure page-shell renderer for the local dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from .html import escape


@dataclass(frozen=True)
class DashboardPageViewModel:
    """Display-ready inputs for the dashboard page shell."""

    sale_year_options: str
    selected_year: str
    source: str
    output: str
    summary_html: str
    selection_inputs_html: str
    notice: str = ""
    error: str = ""
    report_ready: bool = False


def render_dashboard_page(view: DashboardPageViewModel) -> str:
    """Render the page shell without loading data, persisting settings, or calculating tax."""
    message = f'<p class="notice">{escape(view.notice)}</p>' if view.notice else ""
    download = (
        '<p><a class="download" href="/download">Download generated workbook</a></p>' if view.report_ready else ""
    )
    failure = f'<p class="error">{escape(view.error)}</p>' if view.error else ""
    source = escape(view.source)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Capital Gain Estimate Tax Calculator</title><link rel="stylesheet" href="/static/dashboard.css"><script src="/static/dashboard.js" defer></script></head><body><header><h1>Capital Gain Estimate Tax Calculator</h1><p>Understand realized gains and explore estimated taxes.</p></header><main>
    <form class="load-data-form" method="get" action="/dashboard" style="align-items:start"><label>Sale year<select id="sale-year" name="year">{view.sale_year_options}</select></label><label class="source-folder-control">Source folder<input id="source-folder-value" type="hidden" name="source" value="{source}"><span class="source-folder-row"><output id="source-folder-path" class="source-folder-path" title="{source}">{source if source else "No folder selected"}</output><button id="source-folder" class="source-folder-button" type="submit" formaction="/open-realized-gains-root" formmethod="post" formtarget="finder-result">Choose folder</button></span><span id="source-folder-status" class="source-folder-status" role="status"></span></label><label class="load-data-control"><span aria-hidden="true">&nbsp;</span><button class="load-data-button" type="submit" formaction="/dashboard" formmethod="get">Load data</button></label></form><iframe name="finder-result" hidden></iframe><form id="setup-realized-gains-form" method="post" action="/setup-realized-gains-root" target="finder-result" style="display:none"><input id="setup-realized-gains-parent" name="parent"><input id="setup-realized-gains-year" name="year"></form>{message}{download}{failure}{view.summary_html}
    <form class="report-actions" method="post" action="/generate" style="margin-top:18px"><input type="hidden" name="year" value="{escape(view.selected_year)}"><input type="hidden" name="source" value="{source}">{view.selection_inputs_html}<label>Report folder<input name="output" value="{escape(view.output)}" placeholder="…/2026/reports"></label><label class="checkbox"><input name="audit" type="checkbox"> Keep audit files</label><label class="checkbox"><input name="overwrite" type="checkbox" checked> Archive existing report</label><button type="submit">Create Excel report</button></form>
    </main><footer class="app-footer">Developed by DC Technology Consulting · Open-source, free use · <a href="/terms">Terms of Service</a></footer></body></html>'''
