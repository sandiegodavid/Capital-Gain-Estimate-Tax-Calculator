"""Local browser dashboard for reviewing and generating investment reports."""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .application import EstimateTaxes
from .dashboard_data import DashboardData, load_dashboard_data
from .dashboard_selection import DashboardSelection, selection_from_form
from .folder_actions import FinderActionResult, FolderActions
from .models import NormalizedReport, ReportError, totals
from .payment_websites import payment_website
from .settings import (
    SettingsService,
    available_report_years,
    ensure_config_defaults,
    realized_gains_root,
)
from .static_assets import load_static_asset
from .tax_calculation import TaxRateMapping, map_gain_rates
from .tax_estimate import (
    TaxAssumptions,
    estimate_federal_dependent_credits,
    estimated_modified_adjusted_gross_income,
    state_name,
)
from .views.dashboard import DashboardSummaryViewModel, render_dashboard_summary
from .views.dashboard_details import source_selection_inputs
from .views.dashboard_page import DashboardPageViewModel, render_dashboard_page
from .views.loading import render_loading_dashboard
from .views.tax_panel import TaxPanelViewModel, render_tax_panel
from .views.terms import render_terms
from .web_actions import DashboardActions
from .web_http import body_form, finder_result_page, query_form, send_bytes, send_download, send_html

RecordsRootSaver = Callable[[Path], Path | None]
FinderFolderChooser = Callable[[Path | None], Path | None]
RecordsRootProvider = Callable[[], Path | None]
RecordsRootSkeletonCreator = Callable[[Path, int], Path]


def _tax_panel_view_model(
    report: NormalizedReport,
    selection: DashboardSelection,
    assumptions: TaxAssumptions,
    tax_estimator: EstimateTaxes,
) -> TaxPanelViewModel:
    """Convert one completed estimate into display-ready tax-panel values."""
    calculation = tax_estimator.execute(report, assumptions)
    rules = calculation.rules
    formula = calculation.formula
    estimate = formula.estimate
    values = totals(report.lots)
    short_term_gain = values["short_term_gain_loss_usd"]
    long_term_gain = values["long_term_gain_loss_usd"]
    derived_magi = estimated_modified_adjusted_gross_income(
        assumptions.other_ordinary_taxable_income,
        short_term_gain,
        long_term_gain,
    )
    federal_mapping = map_gain_rates(
        rules.calculation_rules,
        formula.other_ordinary_income,
        formula.short_term_gain,
        formula.long_term_gain,
    )
    state_mapping = map_gain_rates(
        rules.calculation_rules,
        formula.other_ordinary_income,
        formula.state_short_term_gain,
        formula.state_long_term_gain,
        rules.standard_deduction("state") + formula.state_dependent_deduction,
    )
    federal_payment = payment_website("US")
    state_payment = payment_website(assumptions.state_code)
    selected_state = state_name(assumptions.state_code)
    return TaxPanelViewModel(
        selection=selection,
        assumptions=assumptions,
        rules=rules,
        formula=formula,
        short_term_gain=short_term_gain,
        long_term_gain=long_term_gain,
        derived_magi=derived_magi,
        dependent_credit_estimate=estimate_federal_dependent_credits(rules, assumptions, derived_magi),
        rate_mapping=TaxRateMapping(
            federal_mapping.federal_short_term,
            federal_mapping.federal_long_term,
            state_mapping.state,
        ),
        state_name=selected_state,
        needs_state_dependents=bool(rules.dependent_benefit_rules),
        federal_payment_url=federal_payment.url if federal_payment else None,
        state_payment_url=(
            state_payment.url
            if rules.state_calculation_supported and estimate.state > 0 and state_payment and selected_state
            else None
        ),
    )


def _render_tax_section(
    report: NormalizedReport,
    selection: DashboardSelection,
    assumptions: TaxAssumptions,
    tax_estimator: EstimateTaxes,
) -> str:
    """Render household inputs and estimates from local jurisdiction rules."""
    return render_tax_panel(_tax_panel_view_model(report, selection, assumptions, tax_estimator))


def _render_dashboard(
    selection: DashboardSelection | None,
    assumptions: TaxAssumptions | None = None,
    notice: str = "",
    error: str = "",
    report_ready: bool = False,
    dashboard_data: DashboardData | None = None,
    tax_estimator: EstimateTaxes | None = None,
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
            if tax_estimator is None:
                raise RuntimeError("Tax estimation must be supplied by the application composition.")
            summary = render_dashboard_summary(
                DashboardSummaryViewModel(
                    report=report,
                    selection=selection,
                    tax_panel=_render_tax_section(report, selection, assumptions or TaxAssumptions(), tax_estimator),
                )
            )
        except (ReportError, OSError) as exc:
            error = str(exc)
    selected_year = selection.year if selection and selection.year is not None else ""
    source = str(selection.source_dir) if selection else (str(root) if root else "")
    output = str(selection.output_dir) if selection else ""
    sorted_years = sorted(years)
    auto_selected = "selected" if not selected_year else ""
    options = f'<option value="" {auto_selected}>Auto-detect</option>'
    options += "".join(
        f'<option value="{year}" {"selected" if year == selected_year else ""}>{year}</option>' for year in sorted_years
    )
    if selected_year and selected_year not in years:
        options += f'<option selected value="{selected_year}">{selected_year}</option>'
    selection_inputs = source_selection_inputs(selection) if selection else ""
    return render_dashboard_page(
        DashboardPageViewModel(
            sale_year_options=options,
            selected_year=str(selected_year),
            source=source,
            output=output,
            summary_html=summary,
            selection_inputs_html=selection_inputs,
            notice=notice,
            error=error,
            report_ready=report_ready,
        )
    )


class InvestmentGainWebApp:
    """HTTP application boundary for the local single-user dashboard."""

    def __init__(
        self,
        records_root_saver: RecordsRootSaver,
        finder_folder_chooser: FinderFolderChooser,
        records_root_skeleton_creator: RecordsRootSkeletonCreator,
        records_root_provider: RecordsRootProvider,
        settings_service: SettingsService,
        tax_estimator: EstimateTaxes,
    ) -> None:
        self.latest_report: Path | None = None
        self.records_root_saver = records_root_saver
        self.finder_folder_chooser = finder_folder_chooser
        self.records_root_skeleton_creator = records_root_skeleton_creator
        self.records_root_provider = records_root_provider
        self.folder_actions = FolderActions(
            records_root_saver,
            finder_folder_chooser,
            records_root_skeleton_creator,
            records_root_provider,
        )
        self.settings_service = settings_service
        self.tax_estimator = tax_estimator
        self.dashboard_actions = DashboardActions(
            self.settings_service,
            partial(_render_dashboard, tax_estimator=self.tax_estimator),
        )

    def handler(self):
        application = self

        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                request = urlparse(self.path)
                if request.path.startswith("/static/"):
                    asset = load_static_asset(request.path)
                    if asset is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                    else:
                        send_bytes(self, asset.payload, asset.content_type)
                    return
                if request.path == "/download" and application.latest_report and application.latest_report.is_file():
                    send_download(self, application.latest_report)
                    return
                if request.path == "/" and not request.query:
                    selection = selection_from_form({})
                    if selection:
                        self._send_html(render_loading_dashboard(selection))
                        return
                if request.path == "/terms":
                    self._send_html(render_terms())
                    return
                if request.path not in ("/", "/dashboard"):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                result = application.dashboard_actions.load(query_form(request.query))
                self._send_html(result.page, result.status)

            def do_POST(self) -> None:  # noqa: N802
                if self.path not in ("/generate", "/open-realized-gains-root", "/setup-realized-gains-root"):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                form = body_form(self.headers, self.rfile)
                if self.path == "/open-realized-gains-root":
                    self._send_finder_result(application.folder_actions.choose_records_root(form))
                    return
                if self.path == "/setup-realized-gains-root":
                    self._send_finder_result(application.folder_actions.create_records_layout(form))
                    return
                result = application.dashboard_actions.generate(form)
                application.latest_report = result.generated_report
                self._send_html(result.page, result.status)

            def _send_html(self, page: str, status: HTTPStatus = HTTPStatus.OK) -> None:
                send_html(self, page, status)

            def _send_finder_result(self, result: FinderActionResult) -> None:
                self._send_html(
                    finder_result_page(
                        result.message,
                        result.ok,
                        result.source,
                        result.setup_parent,
                    ),
                    result.status,
                )

            def log_message(self, *_args: object) -> None:
                return

        return RequestHandler


def run_web_app(host: str = "127.0.0.1", port: int = 8765) -> int:
    """Run the dashboard only on the local computer."""
    from .bootstrap import create_web_application

    ensure_config_defaults()
    server = ThreadingHTTPServer((host, port), create_web_application().handler())
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
