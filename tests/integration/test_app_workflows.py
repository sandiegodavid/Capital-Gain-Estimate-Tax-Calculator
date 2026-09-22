from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from decimal import Decimal
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT / "vendor"))
sys.path.insert(0, str(APP_ROOT))

from capital_gain_estimate_tax_calculator import generate_report, normalize_sources  # noqa: E402
from capital_gain_estimate_tax_calculator.application import EstimateTaxes  # noqa: E402
from capital_gain_estimate_tax_calculator.brokerage_parsing import (
    infer_security_type,
    parse_date,
    parse_decimal,
    split_symbol_cusip,
)  # noqa: E402
from capital_gain_estimate_tax_calculator.dashboard_selection import (  # noqa: E402
    DashboardSelection,
    selection_from_form,
)
from capital_gain_estimate_tax_calculator.finder import picker_start_folder  # noqa: E402
from capital_gain_estimate_tax_calculator.folder_actions import FolderActions  # noqa: E402
from capital_gain_estimate_tax_calculator.normalizer import (  # noqa: E402
    BrokerageNormalizerRegistry,
    CsvSource,
    detect_schema,
)
from capital_gain_estimate_tax_calculator.payment_websites import payment_website  # noqa: E402
from capital_gain_estimate_tax_calculator.report_document import ReportBuilder  # noqa: E402
from capital_gain_estimate_tax_calculator.settings import (
    AppSettings,
    JsonSettingsRepository,
    SettingsService,
    TaxProfileDefaults,
    create_realized_gains_skeleton,
    ensure_config_defaults,
    save_realized_gains_root,
    save_tax_input_defaults,
    tax_input_defaults,
)  # noqa: E402
from capital_gain_estimate_tax_calculator.state_dependent_benefits import (
    estimate_state_dependent_benefits,  # noqa: E402
)
from capital_gain_estimate_tax_calculator.static_assets import load_static_asset  # noqa: E402
from capital_gain_estimate_tax_calculator.tax_calculation import map_bracket_rates  # noqa: E402
from capital_gain_estimate_tax_calculator.tax_domain import (  # noqa: E402
    BracketBand,
    BracketSchedule,
    TaxCalculationRules,
)
from capital_gain_estimate_tax_calculator.tax_estimate import (
    TaxAssumptions,
    assumptions_from_form,
    build_tax_formula,
    estimate_federal_dependent_credits,
    estimate_taxes,
    estimated_modified_adjusted_gross_income,
)  # noqa: E402
from capital_gain_estimate_tax_calculator.tax_rules import TaxRuleStore  # noqa: E402
from capital_gain_estimate_tax_calculator.views.dashboard import (  # noqa: E402
    DashboardSummaryViewModel,
    render_dashboard_summary,
)
from capital_gain_estimate_tax_calculator.views.dashboard_details import (  # noqa: E402
    render_security_group,
    render_sources_section,
)
from capital_gain_estimate_tax_calculator.views.dashboard_page import (  # noqa: E402
    DashboardPageViewModel,
    render_dashboard_page,
)
from capital_gain_estimate_tax_calculator.views.loading import render_loading_dashboard  # noqa: E402
from capital_gain_estimate_tax_calculator.views.tax_panel import render_tax_panel  # noqa: E402
from capital_gain_estimate_tax_calculator.views.terms import render_terms  # noqa: E402
from capital_gain_estimate_tax_calculator.web import (
    InvestmentGainWebApp,
    _render_dashboard,
    _render_tax_section,
    _tax_panel_view_model,
)  # noqa: E402
from capital_gain_estimate_tax_calculator.web_http import (  # noqa: E402
    body_form,
    finder_result_page,
    query_form,
    send_html,
)

CHASE_HEADERS = [
    "Account Name",
    "Account Number",
    "Ticker",
    "CUSIP",
    "Description",
    "Security Type",
    "Quantity",
    "Acquired Date",
    "Sale Date",
    "Market Cost/Proceeds USD",
    "Cost Basis USD",
    "Short Term Realized Gain Loss USD",
    "Long Term Realized Gain Loss USD",
    "Total Realized Gain Loss USD",
    "Disallowed Loss",
]

FIDELITY_HEADERS = [
    "Account",
    "Symbol(CUSIP)",
    "Security Description",
    "Quantity",
    "Date Acquired",
    "Date Sold",
    "Proceeds",
    "Cost Basis",
    "Short Term Gain/Loss",
    "Long Term Gain/Loss",
]

SCHWAB_HEADERS = [
    "Symbol",
    "Name",
    "Closed Date",
    "Quantity",
    "Closing Price",
    "Cost Basis Method",
    "Proceeds",
    "Cost Basis (CB)",
    "Total Gain/Loss ($)",
    "Total Gain/Loss (%)",
    "Long Term (LT) Gain/Loss ($)",
    "Long Term (LT) Gain/Loss (%)",
    "Short Term (ST) Gain/Loss ($)",
    "Short Term (ST) Gain/Loss (%)",
    "Wash Sale?",
    "Disallowed Loss",
]


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


class IntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        write_csv(
            self.source / "chase.csv",
            CHASE_HEADERS,
            [
                [
                    "Brokerage",
                    "TEST-CHASE",
                    "ABC",
                    "TESTCUSIP1",
                    "ABC INC",
                    "Stock",
                    "10",
                    "01/10/2024",
                    "02/20/2026",
                    "$1,000.00",
                    "$900.00",
                    "$0.00",
                    "$100.00",
                    "$100.00",
                    "$0.00",
                ],
                [
                    "Brokerage",
                    "TEST-CHASE",
                    "WASH",
                    "TESTCUSIP2",
                    "WASH SALE INC",
                    "Stock",
                    "1",
                    "01/05/2026",
                    "03/01/2026",
                    "$100.00",
                    "$110.00",
                    "$0.00",
                    "$0.00",
                    "$0.00",
                    "$10.00",
                ],
            ],
        )
        write_csv(
            self.source / "fidelity.csv",
            FIDELITY_HEADERS,
            [
                [
                    "cTEST000",
                    "XYZ(TESTCUSIP3)",
                    "XYZ CORP",
                    "5",
                    "02/01/2026",
                    "04/15/2026",
                    "$500.00",
                    "$450.00",
                    "$50.00",
                    "$0.00",
                ],
                ["Download generated at", "", "", "", "", "", "", "", "", ""],
            ],
        )

    def tearDown(self) -> None:
        self.temp.cleanup()


class HttpAndFolderAdapterTests(IntegrationTestCase):
    def test_http_adapters_parse_forms_and_write_finder_callbacks(self) -> None:
        body = b"year=2026&included_source=chase.csv&included_source=fidelity.csv"

        self.assertEqual(query_form("state=CA&qualified_children=2"), {"state": ["CA"], "qualified_children": ["2"]})
        self.assertEqual(
            body_form({"Content-Length": str(len(body))}, BytesIO(body)),
            {"year": ["2026"], "included_source": ["chase.csv", "fidelity.csv"]},
        )
        callback = finder_result_page("Saved", True, self.source, self.root)
        self.assertIn('"type": "finder-result"', callback)
        self.assertIn(str(self.source), callback)

        class Response:
            def __init__(self) -> None:
                self.status: HTTPStatus | None = None
                self.headers: dict[str, str] = {}
                self.wfile = BytesIO()

            def send_response(self, code: HTTPStatus) -> None:
                self.status = code

            def send_header(self, keyword: str, value: str) -> None:
                self.headers[keyword] = value

            def end_headers(self) -> None:
                return

        response = Response()
        send_html(response, "<p>Ready</p>")
        self.assertEqual(response.status, HTTPStatus.OK)
        self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(response.wfile.getvalue(), b"<p>Ready</p>")

    def test_folder_actions_return_typed_callback_results(self) -> None:
        selected_root = self.root / "Realized Gains"
        selected_root.mkdir()
        actions = FolderActions(
            records_root_saver=lambda path: path,
            finder_folder_chooser=lambda _initial: selected_root,
            records_root_skeleton_creator=lambda parent, _year: parent / "Realized Gains",
            records_root_provider=lambda: self.root,
        )

        choose_result = actions.choose_records_root({"source": [str(self.source)]})
        setup_result = actions.create_records_layout({"parent": [str(self.root)], "year": ["2026"]})

        self.assertTrue(choose_result.ok)
        self.assertEqual(choose_result.source, selected_root)
        self.assertTrue(setup_result.ok)
        self.assertEqual(setup_result.source, self.root / "Realized Gains")
        self.assertIn("2026/source", setup_result.message)


class BrokerageNormalizerIntegrationTests(IntegrationTestCase):
    def test_normalization_preserves_identifiers_and_reconciles(self) -> None:
        report = normalize_sources(self.source, 2026)
        self.assertEqual(len(report.lots), 3)
        self.assertEqual(report.lots[0].account, "TEST-CHASE")
        self.assertEqual({lot.source_name for lot in report.lots}, {"Chase", "Fidelity"})

    def test_normalization_ignores_generated_output_directories(self) -> None:
        report_copy = self.root / "reports" / "audit" / "copied-chase.csv"
        report_copy.parent.mkdir(parents=True)
        write_csv(
            report_copy,
            CHASE_HEADERS,
            [
                [
                    "Brokerage",
                    "TEST-ARCHIVE",
                    "ARCH",
                    "TESTCUSIP4",
                    "ARCHIVE",
                    "Stock",
                    "1",
                    "01/10/2024",
                    "02/20/2026",
                    "$100.00",
                    "$90.00",
                    "$0.00",
                    "$10.00",
                    "$10.00",
                    "$0.00",
                ],
            ],
        )

        report = normalize_sources(self.root, 2026)

        self.assertEqual(len(report.lots), 3)
        self.assertIn("reports/audit/copied-chase.csv", report.ignored_csv_files)

    def test_normalization_ignores_empty_csv_files(self) -> None:
        (self.source / "empty.csv").touch()

        report = normalize_sources(self.source, 2026)

        self.assertEqual(len(report.lots), 3)
        self.assertIn("empty.csv", report.ignored_csv_files)

    def test_filename_selects_chase_mapper_before_header_detection(self) -> None:
        path = self.source / "2026_CHASE_export.csv"
        write_csv(path, FIDELITY_HEADERS, [])

        self.assertEqual(detect_schema(path), "Chase")

    def test_filename_selects_fidelity_mapper_before_header_detection(self) -> None:
        path = self.source / "Fidelity_2026_export.csv"
        write_csv(path, CHASE_HEADERS, [])

        self.assertEqual(detect_schema(path), "Fidelity")

    def test_registry_accepts_an_independent_brokerage_normalizer(self) -> None:
        class ExampleNormalizer:
            schema_name = "Example Brokerage"
            source_note = "Example exports use the supplied settlement date."

            def recognizes_filename(self, source: CsvSource) -> bool:
                return source.path.name == "example-export.csv"

            def recognizes(self, source: CsvSource) -> bool:
                return self.recognizes_filename(source)

            def normalize(self, source: CsvSource):
                return []

        normalizer = ExampleNormalizer()
        registry = BrokerageNormalizerRegistry((normalizer,))
        source = CsvSource(self.source / "example-export.csv", "example-export.csv")

        self.assertIs(registry.resolve(source), normalizer)
        self.assertIs(registry.for_schema("Example Brokerage"), normalizer)

    def test_shared_brokerage_parsing_is_independent_of_a_normalizer(self) -> None:
        symbol, cusip = split_symbol_cusip("ABC(012345678)", "ABC INC")

        self.assertEqual(parse_decimal("($1,234.50)"), Decimal("-1234.50"))
        self.assertEqual(parse_date("2026-02-20").isoformat(), "2026-02-20")
        self.assertEqual((symbol, cusip), ("ABC", "012345678"))
        self.assertEqual(infer_security_type("ABC260220C00100000", "CALL ABC"), "Option")

    def test_schwab_mapper_handles_title_rows_and_wash_sale_adjustments(self) -> None:
        path = self.source / "Charles_Schwab_realized_gain_loss.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Realized Gain/Loss for account"])
            writer.writerow(SCHWAB_HEADERS)
            writer.writerow(
                [
                    "SCHW",
                    "SCHWAB SAMPLE",
                    "01/02/2026",
                    "10",
                    "$100.00",
                    "FIFO",
                    "$1,000.00",
                    "$950.00",
                    "$100.00",
                    "10.5%",
                    "--",
                    "--",
                    "$100.00",
                    "10.5%",
                    "Yes",
                    "$50.00",
                ]
            )

        report = normalize_sources(self.source, 2026)
        schwab_lot = next(lot for lot in report.lots if lot.source_name == "Charles Schwab")

        self.assertEqual(detect_schema(path), "Charles Schwab")
        self.assertEqual(schwab_lot.symbol, "SCHW")
        self.assertEqual(schwab_lot.acquired_date, schwab_lot.sale_date)
        self.assertEqual(schwab_lot.total_realized_gain_loss_usd, Decimal("100"))
        self.assertEqual(schwab_lot.disallowed_loss_usd, Decimal("50"))
        self.assertIn("Account / brokerage", render_security_group("SCHW", [schwab_lot]))
        self.assertIn(">Charles Schwab</td>", render_security_group("SCHW", [schwab_lot]))
        source_section = render_sources_section(
            report,
            DashboardSelection(self.source, self.root / "reports", 2026),
        )
        self.assertIn("Charles Schwab source note", source_section)
        self.assertIn("closed date is shown as the acquisition-date placeholder", source_section)

    def test_schwab_headers_are_detected_without_a_brokerage_filename(self) -> None:
        path = self.source / "broker_export.csv"
        write_csv(path, SCHWAB_HEADERS, [])

        self.assertEqual(detect_schema(path), "Charles Schwab")


class DashboardRenderingTests(IntegrationTestCase):
    def test_dashboard_summary_renderer_uses_prebuilt_view_model(self) -> None:
        report = normalize_sources(self.source, 2026)
        selection = DashboardSelection(self.source, self.root / "reports", 2026)

        page = render_dashboard_summary(
            DashboardSummaryViewModel(
                report=report,
                selection=selection,
                tax_panel='<section id="prebuilt-tax-panel">Tax panel</section>',
            )
        )

        self.assertIn('id="prebuilt-tax-panel"', page)
        self.assertIn("Security summary", page)
        self.assertIn("Included sources", page)

    def test_dashboard_page_renderer_uses_prebuilt_view_model(self) -> None:
        page = render_dashboard_page(
            DashboardPageViewModel(
                sale_year_options='<option selected value="2026">2026</option>',
                selected_year="2026",
                source="/example/source&folder",
                output="/example/reports",
                summary_html='<section id="prebuilt-summary">Summary</section>',
                selection_inputs_html='<input type="hidden" name="included_source" value="source.csv">',
                notice="Saved & ready",
                report_ready=True,
            )
        )

        self.assertIn('id="prebuilt-summary"', page)
        self.assertIn("Saved &amp; ready", page)
        self.assertIn("/example/source&amp;folder", page)
        self.assertIn('name="included_source"', page)
        self.assertIn('href="/static/dashboard.css"', page)
        self.assertIn('src="/static/dashboard.js"', page)

    def test_dashboard_static_styles_preserve_rate_and_result_card_grids(self) -> None:
        stylesheet = load_static_asset("/static/dashboard.css")

        self.assertIsNotNone(stylesheet)
        assert stylesheet is not None
        css = stylesheet.payload.decode("utf-8")
        self.assertIn(".mapped-rates{display:grid;grid-template-columns:repeat(3,1fr)", css)
        self.assertIn(".tax-results{display:grid;grid-template-columns:repeat(3,1fr)", css)


class BrokerageTermClassificationTests(IntegrationTestCase):
    def test_schwab_mapper_uses_populated_gain_loss_columns_for_tax_term(self) -> None:
        path = self.source / "Schwab_terms.csv"
        write_csv(
            path,
            SCHWAB_HEADERS,
            [
                [
                    "LT",
                    "LONG TERM",
                    "01/02/2026",
                    "10",
                    "$100.00",
                    "FIFO",
                    "$1,000.00",
                    "$900.00",
                    "$100.00",
                    "11.1%",
                    "$100.00",
                    "11.1%",
                    "--",
                    "--",
                    "No",
                    "--",
                ],
                [
                    "ST",
                    "SHORT TERM",
                    "01/03/2026",
                    "10",
                    "$100.00",
                    "FIFO",
                    "$1,000.00",
                    "$1,200.00",
                    "($200.00)",
                    "-16.7%",
                    "--",
                    "--",
                    "($200.00)",
                    "-16.7%",
                    "No",
                    "--",
                ],
            ],
        )

        lots = {lot.symbol: lot for lot in normalize_sources(self.source, 2026).lots}

        self.assertEqual(lots["LT"].long_term_gain_loss_usd, Decimal("100"))
        self.assertEqual(lots["LT"].short_term_gain_loss_usd, Decimal("0"))
        self.assertEqual(lots["LT"].tax_term, "Long-Term")
        self.assertEqual(lots["ST"].short_term_gain_loss_usd, Decimal("-200"))
        self.assertEqual(lots["ST"].long_term_gain_loss_usd, Decimal("0"))
        self.assertEqual(lots["ST"].tax_term, "Short-Term")


class WebRouteAndSelectionTests(IntegrationTestCase):
    def web_app(self, **overrides: object) -> InvestmentGainWebApp:
        dependencies: dict[str, object] = {
            "records_root_saver": lambda root: root,
            "finder_folder_chooser": lambda _initial=None: None,
            "records_root_skeleton_creator": lambda parent, _year: parent / "Realized Gains",
            "records_root_provider": lambda: None,
            "settings_service": SettingsService(JsonSettingsRepository(self.root / "config.local.json")),
            "tax_estimator": EstimateTaxes(TaxRuleStore()),
        }
        dependencies.update(overrides)
        return InvestmentGainWebApp(**dependencies)  # type: ignore[arg-type]

    def test_dashboard_load_request_renders_report_data(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.web_app().handler())
        thread = Thread(target=server.handle_request)
        thread.start()
        query = urlencode({"source": str(self.source), "year": ""})
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/dashboard?{query}") as response:
                page = response.read().decode("utf-8")
        finally:
            thread.join(timeout=2)
            server.server_close()

        self.assertIn("Security summary", page)
        self.assertIn("2026", page)

    def test_source_folder_click_opens_configured_records_root_in_finder(self) -> None:
        saved_roots: list[Path] = []
        app = self.web_app(
            records_root_saver=saved_roots.append,
            finder_folder_chooser=lambda _initial=None: self.root,
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler())
        thread = Thread(target=server.handle_request)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/open-realized-gains-root",
                data=b"",
                method="POST",
            )
            with urlopen(request) as response:
                payload = response.read().decode("utf-8")
        finally:
            thread.join(timeout=2)
            server.server_close()

        self.assertIn('"type": "finder-result"', payload)
        self.assertIn("Realized gains folder saved.", payload)
        self.assertIn(str(self.root), payload)
        self.assertEqual(saved_roots, [self.root])

    def test_source_folder_click_opens_finder_without_a_configured_root(self) -> None:
        saved_roots: list[Path] = []
        app = self.web_app(
            records_root_saver=saved_roots.append,
            finder_folder_chooser=lambda _initial=None: self.root,
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler())
        thread = Thread(target=server.handle_request)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/open-realized-gains-root",
                data=b"",
                method="POST",
            )
            with urlopen(request) as response:
                payload = response.read().decode("utf-8")
        finally:
            thread.join(timeout=2)
            server.server_close()

        self.assertIn("Realized gains folder saved.", payload)
        self.assertEqual(saved_roots, [self.root])

    def test_source_folder_click_opens_chooser_at_existing_source(self) -> None:
        initial_folders: list[Path | None] = []

        def choose_folder(initial_folder: Path | None) -> Path:
            initial_folders.append(initial_folder)
            return self.root

        app = self.web_app(
            finder_folder_chooser=choose_folder,
            records_root_provider=lambda: self.root,
            records_root_saver=lambda root: root,
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler())
        thread = Thread(target=server.handle_request)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/open-realized-gains-root",
                data=urlencode({"source": str(self.source)}).encode(),
                method="POST",
            )
            with urlopen(request) as response:
                payload = response.read().decode("utf-8")
        finally:
            thread.join(timeout=2)
            server.server_close()

        self.assertIn("Realized gains folder saved.", payload)
        self.assertEqual(initial_folders, [self.root])

    def test_picker_start_folder_prefers_records_root_only_when_source_is_present(self) -> None:
        self.assertEqual(picker_start_folder(str(self.source), self.root), self.root)
        self.assertEqual(picker_start_folder(str(self.source), None), self.source)
        self.assertIsNone(picker_start_folder("", self.root))

    def test_records_layout_setup_creates_source_and_reports_folders(self) -> None:
        parent = self.root / "new-records-parent"
        parent.mkdir()
        config_path = self.root / "config.local.json"

        root = create_realized_gains_skeleton(parent, 2026, config_path)

        self.assertEqual(root, (parent / "Realized Gains").resolve())
        self.assertTrue((root / "2026" / "source").is_dir())
        self.assertTrue((root / "2026" / "reports").is_dir())

    def test_records_layout_setup_endpoint_returns_source_file_instruction(self) -> None:
        created: list[tuple[Path, int]] = []

        def create_skeleton(parent: Path, year: int) -> Path:
            created.append((parent, year))
            return parent / "Realized Gains"

        app = self.web_app(records_root_skeleton_creator=create_skeleton)
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler())
        thread = Thread(target=server.handle_request)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.server_port}/setup-realized-gains-root",
                data=urlencode({"parent": str(self.root), "year": "2026"}).encode(),
                method="POST",
            )
            with urlopen(request) as response:
                payload = response.read().decode("utf-8")
        finally:
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(created, [(self.root, 2026)])
        self.assertIn("Put brokerage CSV files in", payload)
        self.assertIn(str(self.root / "Realized Gains" / "2026" / "source"), payload)

    def test_selection_resolves_records_root_year_folder_and_source_folder(self) -> None:
        records_root = self.root / "Realized Gains"
        older_source = records_root / "2025" / "source"
        newer_source = records_root / "2026" / "source"
        older_source.mkdir(parents=True)
        newer_source.mkdir(parents=True)

        from_root = selection_from_form({"source": [str(records_root)], "year": [""]})
        from_year = selection_from_form({"source": [str(records_root / "2025")], "year": [""]})
        from_source = selection_from_form({"source": [str(newer_source)], "year": [""]})

        self.assertEqual(
            from_root, DashboardSelection(newer_source, (records_root / "2026" / "reports").resolve(), 2026)
        )
        self.assertEqual(
            from_year, DashboardSelection(older_source, (records_root / "2025" / "reports").resolve(), 2025)
        )
        self.assertEqual(
            from_source, DashboardSelection(newer_source, (records_root / "2026" / "reports").resolve(), 2026)
        )

    def test_selection_keeps_a_direct_csv_folder_for_year_auto_detection(self) -> None:
        selection = selection_from_form({"source": [str(self.source)], "year": [""]})
        self.assertEqual(selection, DashboardSelection(self.source, (self.root / "reports").resolve(), None))

    def test_failed_load_keeps_source_path_and_auto_detect_option_visible(self) -> None:
        source = self.root / "missing-source"
        page = _render_dashboard(
            DashboardSelection(source, self.root / "reports", None), error="Input directory does not exist"
        )
        self.assertIn(f'value="{source}"', page)
        self.assertIn('value="" selected>Auto-detect</option>', page)
        self.assertIn('formaction="/open-realized-gains-root"', page)
        self.assertIn('formtarget="finder-result"', page)
        self.assertIn('action="/setup-realized-gains-root"', page)
        self.assertIn('id="setup-realized-gains-form"', page)
        self.assertIn('src="/static/dashboard.js"', page)
        self.assertIn('src="/static/dashboard.js"', page)
        self.assertIn('class="load-data-form"', page)
        self.assertIn('class="source-folder-row"', page)
        self.assertIn(">Choose folder</button>", page)
        self.assertIn('id="source-folder-path"', page)
        self.assertIn('action="/dashboard"', page)
        self.assertIn(">Load data</button>", page)


class TaxAndSettingsIntegrationTests(IntegrationTestCase):
    def test_bracket_mapper_selects_rates_for_taxable_income(self) -> None:
        rules = TaxCalculationRules(
            BracketSchedule((BracketBand(Decimal("50000"), Decimal("0.12")), BracketBand(None, Decimal("0.22")))),
            BracketSchedule((BracketBand(Decimal("50000"), Decimal("0")), BracketBand(None, Decimal("0.15")))),
            BracketSchedule((BracketBand(Decimal("70000"), Decimal("0.05")), BracketBand(None, Decimal("0.08")))),
            Decimal("0"),
            Decimal("0"),
        )
        mapping = map_bracket_rates(rules, Decimal("60000"))
        self.assertEqual(mapping.federal_short_term.rate, Decimal("0.22"))
        self.assertEqual(mapping.federal_long_term.rate, Decimal("0.15"))
        self.assertEqual(mapping.state.rate, Decimal("0.05"))

    def test_local_tax_rules_calculate_each_gain_type_incrementally(self) -> None:
        report = normalize_sources(self.source, 2026)
        rules = TaxRuleStore().load(2026, "CA", "single")
        assumptions = TaxAssumptions(state_code="CA", other_ordinary_taxable_income=Decimal("84980"))
        estimate = estimate_taxes(report, assumptions, rules)
        formula = build_tax_formula(rules, Decimal("84980"), Decimal("50"), Decimal("100"))
        self.assertEqual(formula.federal_standard_deduction, Decimal("16100"))
        self.assertEqual(formula.state_standard_deduction, Decimal("5706"))
        self.assertGreater(estimate.federal_short_term, Decimal("0"))
        self.assertGreater(estimate.state, Decimal("0"))
        self.assertEqual(
            sum(component.taxable_amount for component in formula.state.total_components), formula.state.closing_income
        )
        self.assertEqual(formula.estimate, estimate)
        remaining_deduction_formula = build_tax_formula(rules, Decimal("10000"), Decimal("50"), Decimal("6000"))
        self.assertEqual(remaining_deduction_formula.remaining_standard_deduction, Decimal("6050"))
        self.assertEqual(remaining_deduction_formula.federal_long_term.closing_income, Decimal("0"))

    def test_long_term_gains_stack_above_ordinary_income_and_capital_results_cross_net(self) -> None:
        rules = TaxRuleStore().load(2026, "CA", "single")
        stacked = build_tax_formula(rules, Decimal("60000"), Decimal("0"), Decimal("10000"))
        self.assertEqual(stacked.federal_long_term.opening_income, Decimal("43900"))
        self.assertEqual(stacked.federal_long_term.closing_income, Decimal("53900"))
        self.assertEqual(stacked.federal_long_term.tax_amount, Decimal("667.50"))

        netted = build_tax_formula(rules, Decimal("60000"), Decimal("-5000"), Decimal("10000"))
        self.assertEqual(netted.short_term_gain, Decimal("0"))
        self.assertEqual(netted.long_term_gain, Decimal("5000"))

    def test_payment_website_uses_jurisdiction_tax_data(self) -> None:
        california = payment_website("CA")
        self.assertIsNotNone(california)
        self.assertEqual(california.url, "https://www.ftb.ca.gov/pay/index.html")
        federal = payment_website("US")
        self.assertIsNotNone(federal)
        self.assertEqual(federal.url, "https://www.irs.gov/payments")
        self.assertEqual(payment_website("TX"), None)

    def test_tax_inputs_persist_without_replacing_other_local_settings(self) -> None:
        config_path = self.root / "config.local.json"
        config_path.write_text(json.dumps({"custom_setting": "preserved"}), encoding="utf-8")
        save_tax_input_defaults(
            {
                "state": ["ca"],
                "other_ordinary_taxable_income": ["12,345.67"],
                "filing_status": ["head_of_household"],
                "qualified_children": ["2"],
                "other_dependents": ["1"],
                "state_eligible_dependents": ["3"],
            },
            config_path,
        )
        self.assertEqual(tax_input_defaults(config_path), ("CA", "12345.67"))
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["custom_setting"], "preserved")
        self.assertEqual(saved["filing_status"], "head_of_household")
        self.assertEqual(saved["qualified_children"], 2)
        self.assertEqual(saved["other_dependents"], 1)
        self.assertEqual(saved["state_eligible_dependents_by_state"], {"CA": 3})
        self.assertNotIn("modified_adjusted_gross_income", saved)

    def test_settings_service_updates_typed_profile_and_preserves_other_settings(self) -> None:
        config_path = self.root / "config.local.json"
        config_path.write_text(
            json.dumps({"custom_setting": "preserved", "state_eligible_dependents_by_state": {"NY": 1}}),
            encoding="utf-8",
        )
        service = SettingsService(JsonSettingsRepository(config_path))

        service.save_tax_profile(
            {
                "state": ["ca"],
                "qualified_children": ["2"],
                "other_dependents": ["invalid"],
                "state_eligible_dependents": ["3"],
            }
        )

        settings = service.load()
        self.assertEqual(settings.tax_profile.state_code, "CA")
        self.assertEqual(settings.tax_profile.qualified_children, 2)
        self.assertEqual(settings.tax_profile.other_dependents, 0)
        self.assertEqual(settings.tax_profile.state_eligible_dependents("CA"), 3)
        self.assertEqual(settings.tax_profile.state_eligible_dependents("NY"), 1)
        self.assertEqual(settings.additional_values, {"custom_setting": "preserved"})

    def test_config_defaults_never_seed_an_example_records_root(self) -> None:
        config_path = self.root / "config.local.json"
        example_path = self.root / "config.example.json"
        example_path.write_text(
            json.dumps(
                {
                    "filing_status": "head_of_household",
                    "realized_gains_root": "/path/to/example/Realized Gains",
                }
            ),
            encoding="utf-8",
        )

        settings = ensure_config_defaults(config_path, example_path)

        self.assertEqual(settings["filing_status"], "head_of_household")
        self.assertNotIn("realized_gains_root", settings)

        self.assertIsNone(
            AppSettings.from_mapping(
                {"realized_gains_root": "/path/to/Financial Records/Investments/Realized Gains"}
            ).records.realized_gains_root
        )

    def test_tax_assumptions_accept_injected_typed_defaults(self) -> None:
        assumptions = assumptions_from_form(
            {"state": ["OR"]},
            TaxProfileDefaults(
                filing_status="head_of_household",
                qualified_children=2,
                other_dependents=1,
                other_ordinary_taxable_income="12000",
                state_eligible_dependents_by_state={"OR": 3},
            ),
        )

        self.assertEqual(assumptions.state_code, "OR")
        self.assertEqual(assumptions.filing_status, "head_of_household")
        self.assertEqual(assumptions.qualified_children, 2)
        self.assertEqual(assumptions.other_dependents, 1)
        self.assertEqual(assumptions.state_eligible_dependents, 3)
        self.assertEqual(assumptions.other_ordinary_taxable_income, Decimal("12000"))

    def test_records_root_persists_without_replacing_other_local_settings(self) -> None:
        config_path = self.root / "config.local.json"
        config_path.write_text(json.dumps({"custom_setting": "preserved"}), encoding="utf-8")
        parent = self.root / "Investments"
        records_root = parent / "Realized Gains"
        records_root.mkdir(parents=True)

        save_realized_gains_root(parent, config_path)

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["realized_gains_root"], str(records_root.resolve()))
        self.assertEqual(saved["custom_setting"], "preserved")

    def test_records_root_accepts_the_realized_gains_folder_itself(self) -> None:
        config_path = self.root / "config.local.json"
        records_root = self.root / "Realized Gains"
        records_root.mkdir()

        save_realized_gains_root(records_root, config_path)

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["realized_gains_root"], str(records_root.resolve()))

    def test_records_root_rejects_a_parent_without_realized_gains(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not contain a Realized Gains folder"):
            save_realized_gains_root(self.root / "source", self.root / "config.local.json")


class TaxPanelRenderingTests(IntegrationTestCase):
    def test_tax_panel_uses_local_rules_and_accessible_help(self) -> None:
        report = normalize_sources(self.source, 2026)
        selection = DashboardSelection(self.source, self.root / "reports", 2026)
        page = _render_tax_section(
            report,
            selection,
            TaxAssumptions(state_code="CA", qualified_children=2, other_dependents=1),
            EstimateTaxes(TaxRuleStore()),
        )
        self.assertNotIn('name="ai_provider"', page)
        self.assertNotIn("rate guidance", page.lower())
        self.assertIn('name="qualified_children"', page)
        self.assertIn('name="other_dependents"', page)
        self.assertIn('name="state_eligible_dependents"', page)
        self.assertIn("State-eligible dependents", page)
        self.assertIn('name="other_ordinary_taxable_income"', page)
        self.assertIn("Short-term loss carryover ($)", page)
        self.assertIn("Long-term loss carryover ($)", page)
        self.assertIn("#ordinary-income::-webkit-inner-spin-button", page)
        self.assertNotIn("#qualified-children::-webkit-inner-spin-button", page)
        self.assertIn('name="other_ordinary_taxable_income" type="number"', page)
        self.assertLess(page.index('id="ordinary-income"'), page.index('id="short-term-carryover-loss"'))
        self.assertLess(page.index('id="short-term-carryover-loss"'), page.index('id="long-term-carryover-loss"'))
        self.assertIn(".tax-field-second-row { grid-row:2 }", page)
        self.assertIn(".tax-form { grid-template-columns:repeat(4,minmax(160px,1fr));", page)
        self.assertNotIn('name="modified_adjusted_gross_income"', page)
        self.assertIn(
            "wages; taxable interest and dividends; retirement or taxable Social Security income; business or self-employment income; rental or K-1 income; income not included in the imported realized-gains files; and any other taxable income.",
            page,
        )
        self.assertIn("derived planning MAGI", page)
        self.assertIn('aria-label="Help for CTC-eligible children"', page)
        self.assertIn('aria-label="Help for Other credit-eligible dependents"', page)
        self.assertIn('aria-label="Help for Short-term loss carryover ($)"', page)
        self.assertIn('aria-label="Help for Long-term loss carryover ($)"', page)
        self.assertIn('id="tax-rules-dialog"', page)
        self.assertIn(">View tax rules</button>", page)
        self.assertIn(">Tax brackets</h4>", page)
        self.assertIn(">Standard deduction</h4>", page)
        self.assertIn(">Credits</h4>", page)
        self.assertIn("Child tax credit", page)
        self.assertIn("Estimated federal child/dependent credits", page)
        self.assertIn("Additional Child Tax Credit (ACTC)", page)
        self.assertIn("Earned Income Tax Credit (EITC)", page)
        self.assertNotIn("Add bracket", page)

        self.assertIn("https://www.irs.gov/payments", page)
        self.assertIn("See exact formula", page)
        self.assertIn("Exact tax formula", page)
        self.assertIn('id="tax-estimate-output"', page)
        self.assertIn('id="tax-estimate-stale"', page)
        self.assertIn('id="tax-estimate-form"', page)
        self.assertIn(
            'Estimate inputs changed. Click <button class="tax-estimate-stale-action" type="submit" form="tax-estimate-form">Update estimate</button> to calculate with these values.',
            page,
        )
        self.assertIn("saved=sessionStorage.getItem(key)", page)
        self.assertIn("output.hidden=true;stale.hidden=false", page)
        self.assertIn('stateDependents=document.getElementById("state-eligible-dependents")', page)
        self.assertIn('stateDependents.value=""', page)
        self.assertIn(
            "#qualified-children,#other-dependents,#state-eligible-dependents,#ordinary-income,#short-term-carryover-loss,#long-term-carryover-loss",
            page,
        )
        self.assertIn("form.requestSubmit()", page)

    def test_tax_panel_renderer_uses_prebuilt_view_model(self) -> None:
        report = normalize_sources(self.source, 2026)
        selection = DashboardSelection(self.source, self.root / "reports", 2026)
        view = _tax_panel_view_model(
            report,
            selection,
            TaxAssumptions(state_code="CA", qualified_children=1),
            EstimateTaxes(TaxRuleStore()),
        )

        page = render_tax_panel(
            replace(
                view,
                state_name="Example State",
                federal_payment_url=None,
                state_payment_url="https://example.test/pay-state-tax",
            )
        )

        self.assertIn("Pay Example State estimated tax", page)
        self.assertNotIn("Pay federal estimated tax", page)


class TaxCalculationAndBenefitTests(IntegrationTestCase):
    def test_federal_dependent_credit_uses_confirmed_counts_and_derived_magi_phaseout(self) -> None:
        rules = TaxRuleStore().load(2026, "CA", "single")
        assumptions = TaxAssumptions(qualified_children=2, other_dependents=1)
        full_credit = estimate_federal_dependent_credits(
            rules,
            assumptions,
            estimated_modified_adjusted_gross_income(Decimal("190000"), Decimal("5000"), Decimal("5000")),
        )
        phased_credit = estimate_federal_dependent_credits(
            rules,
            assumptions,
            estimated_modified_adjusted_gross_income(Decimal("191001"), Decimal("5000"), Decimal("5000")),
        )

        self.assertEqual(full_credit.amount, Decimal("4900"))
        self.assertEqual(phased_credit.phaseout_reduction, Decimal("100"))
        self.assertEqual(phased_credit.amount, Decimal("4800"))

    def test_no_income_tax_state_and_unsupported_state_are_explicit(self) -> None:
        texas = TaxRuleStore().load(2026, "TX", "single")
        washington = TaxRuleStore().load(2026, "WA", "single")
        self.assertTrue(texas.state_calculation_supported)
        self.assertIn("no broad individual income tax", texas.state_notice)
        self.assertFalse(washington.state_calculation_supported)
        self.assertIn("unsupported", washington.state_notice)

    def test_supported_state_capital_gain_and_dependent_rules_are_applied(self) -> None:
        arkansas = TaxRuleStore().load(2026, "AR", "single")
        missouri = TaxRuleStore().load(2026, "MO", "single")
        new_mexico = TaxRuleStore().load(2026, "NM", "single")
        georgia = TaxRuleStore().load(2026, "GA", "married_filing_jointly", qualified_children=2, other_dependents=1)

        self.assertEqual(
            arkansas.state_taxable_gains(Decimal("100"), Decimal("1000")), (Decimal("100"), Decimal("500.0"))
        )
        self.assertEqual(missouri.state_taxable_gains(Decimal("100"), Decimal("1000")), (Decimal("0"), Decimal("0")))
        self.assertEqual(
            new_mexico.state_taxable_gains(Decimal("100"), Decimal("10000")), (Decimal("100"), Decimal("6000.0"))
        )
        self.assertEqual(georgia.standard_deduction("state"), Decimal("30000"))

    def test_state_dependent_benefits_require_state_confirmation_and_keep_credits_separate(self) -> None:
        georgia = TaxRuleStore().load(2026, "GA", "single")
        assumptions = TaxAssumptions(state_code="GA", state_eligible_dependents=2)
        formula = build_tax_formula(georgia, Decimal("60000"), Decimal("1000"), Decimal("0"), assumptions=assumptions)
        self.assertEqual(formula.state_standard_deduction, Decimal("15000"))
        self.assertEqual(formula.state_dependent_deduction, Decimal("10000"))
        missing = estimate_state_dependent_benefits(
            georgia, TaxAssumptions(state_code="GA"), {"state_agi": Decimal("60000")}, {}
        )
        self.assertEqual(missing.lines[0].outcome, "requires_more_inputs")

        arkansas = TaxRuleStore().load(2026, "AR", "single")
        credit = estimate_state_dependent_benefits(
            arkansas,
            TaxAssumptions(state_code="AR", state_eligible_dependents=2),
            {"state_agi": Decimal("60000")},
            {"state_eligible_dependents": 2},
            Decimal("40"),
        )
        self.assertEqual(credit.potential_nonrefundable_credit, Decimal("58"))
        self.assertEqual(credit.applied_nonrefundable_credit, Decimal("40"))
        self.assertEqual(credit.lines[0].outcome, "potential_only")

        california = TaxRuleStore().load(2026, "CA", "single")
        provisional = estimate_state_dependent_benefits(
            california,
            TaxAssumptions(state_code="CA", state_eligible_dependents=2),
            {"state_agi": Decimal("60000")},
            {"state_eligible_dependents": 2},
        )
        self.assertEqual(provisional.lines[0].outcome, "unsupported")
        self.assertTrue(provisional.lines[0].provisional)


class ReportWorkflowTests(IntegrationTestCase):
    def test_end_to_end_workbook_structure_and_numeric_types(self) -> None:
        output_dir = self.root / "reports"
        output_path, summary = generate_report(
            self.source,
            year=2026,
            output_dir=output_dir,
            overwrite=False,
            keep_audit_files=True,
        )
        self.assertTrue(output_path.exists())
        self.assertTrue(summary["reconciliation_ok"])
        with zipfile.ZipFile(output_path) as workbook:
            part_names = set(workbook.namelist())
            self.assertIn("xl/workbook.xml", part_names)
            self.assertIn("xl/worksheets/sheet3.xml", part_names)
            workbook_xml = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
            namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            sheet_names = [sheet.attrib["name"] for sheet in workbook_xml.findall("x:sheets/x:sheet", namespace)]
            self.assertEqual(sheet_names, ["Summary", "Security Summary", "Realized Lots", "Checks", "Source Notes"])
            lots_xml = ElementTree.fromstring(workbook.read("xl/worksheets/sheet3.xml"))
            cells = {cell.attrib["r"]: cell for cell in lots_xml.findall(".//x:c", namespace)}
            self.assertEqual(cells["F5"].attrib.get("t"), None)
            self.assertEqual(cells["G5"].attrib.get("t"), None)
            self.assertEqual(cells["I5"].attrib.get("t"), None)
            self.assertIsNotNone(cells["O5"].find("x:f", namespace))
            self.assertEqual(cells["R5"].attrib.get("t"), None)
            self.assertIsNone(lots_xml.find("x:dataValidations", namespace))
        self.assertTrue((output_dir / "audit" / "2026" / "summary.json").exists())

    def test_report_builder_interprets_content_without_creating_a_workbook(self) -> None:
        document = ReportBuilder().build(normalize_sources(self.source, 2026))

        self.assertEqual(document.sources_text, "Chase and Fidelity")
        self.assertEqual(document.lot_first_sale.isoformat(), "2026-02-20")
        self.assertEqual(document.lot_last_sale.isoformat(), "2026-04-15")
        self.assertEqual([security.symbol for security in document.securities], ["ABC", "WASH", "XYZ"])
        self.assertEqual(document.report_months, (1, 2, 3, 4))
        self.assertEqual(document.conventions[0], ("Currency", "USD"))
        self.assertEqual(document.content.lots_headers[0], "Source")
        self.assertEqual(document.content.checks_headers[-1], "Notes")
        self.assertEqual(document.audit_checks[0].code, "transaction_count")
        self.assertIn("source_count:Chase", [check.code for check in document.audit_checks])


class StandaloneRenderingTests(IntegrationTestCase):
    def test_terms_renderer_is_a_pure_standalone_view(self) -> None:
        page = render_terms()

        self.assertIn("Terms of Service", page)
        self.assertIn("DC Technology Consulting assumes no liability", page)
        self.assertIn('href="/"', page)

    def test_loading_renderer_preserves_dashboard_selection_in_the_request_url(self) -> None:
        selection = DashboardSelection(
            source_dir=self.source,
            output_dir=self.root / "reports",
            year=2026,
            included_source_files=("chase.csv",),
        )

        page = render_loading_dashboard(selection)

        self.assertIn("/dashboard?source=", page)
        self.assertIn("year=2026", page)
        self.assertIn("source_selection=1", page)
        self.assertIn("included_source=chase.csv", page)


class ReportGenerationBehaviorTests(IntegrationTestCase):
    def test_existing_report_requires_overwrite(self) -> None:
        output_dir = self.root / "reports"
        generate_report(self.source, year=2026, output_dir=output_dir)
        with self.assertRaisesRegex(Exception, "already exists"):
            generate_report(self.source, year=2026, output_dir=output_dir)


if __name__ == "__main__":
    unittest.main()
