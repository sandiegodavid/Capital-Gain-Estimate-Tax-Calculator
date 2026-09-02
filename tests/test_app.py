from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
import zipfile
from decimal import Decimal
from http.server import ThreadingHTTPServer
from threading import Thread
from xml.etree import ElementTree
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "vendor"))
sys.path.insert(0, str(APP_ROOT))

from capital_gain_estimate_tax_calculator import generate_report, normalize_sources  # noqa: E402
from capital_gain_estimate_tax_calculator.normalizer import detect_schema  # noqa: E402
from capital_gain_estimate_tax_calculator.finder import picker_start_folder  # noqa: E402
from capital_gain_estimate_tax_calculator.dashboard_selection import DashboardSelection, selection_from_form  # noqa: E402
from capital_gain_estimate_tax_calculator.tax_estimate import TaxAssumptions, build_tax_formula, estimate_taxes  # noqa: E402
from capital_gain_estimate_tax_calculator.guidance_prompt import TaxGuidancePromptBuilder  # noqa: E402
from capital_gain_estimate_tax_calculator.guidance_providers import parse_gemini_response, parse_openrouter_response  # noqa: E402
from capital_gain_estimate_tax_calculator.guidance_mapping import map_bracket_rates, map_gain_rates, validate_guidance_response  # noqa: E402
from capital_gain_estimate_tax_calculator.payment_websites import payment_website  # noqa: E402
from capital_gain_estimate_tax_calculator.settings import editable_config, ensure_config_defaults, create_realized_gains_skeleton, save_editable_config, save_realized_gains_root, save_tax_input_defaults, tax_input_defaults  # noqa: E402
from capital_gain_estimate_tax_calculator.guidance_store import GuidanceResponseStore  # noqa: E402
from capital_gain_estimate_tax_calculator.guidance_profile import GuidanceProfile  # noqa: E402
from capital_gain_estimate_tax_calculator.guidance_review import GuidanceReviewService  # noqa: E402
from capital_gain_estimate_tax_calculator.tax_guidance import TaxGuidanceService  # noqa: E402
from capital_gain_estimate_tax_calculator.web import InvestmentGainWebApp, _render_config_modal, _render_dashboard, _render_tax_section  # noqa: E402


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


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


class InvestmentGainAppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        write_csv(
            self.source / "chase.csv",
            CHASE_HEADERS,
            [
                ["Brokerage", "TEST-CHASE", "ABC", "TESTCUSIP1", "ABC INC", "Stock", "10", "01/10/2024", "02/20/2026", "$1,000.00", "$900.00", "$0.00", "$100.00", "$100.00", "$0.00"],
                ["Brokerage", "TEST-CHASE", "WASH", "TESTCUSIP2", "WASH SALE INC", "Stock", "1", "01/05/2026", "03/01/2026", "$100.00", "$110.00", "$0.00", "$0.00", "$0.00", "$10.00"],
            ],
        )
        write_csv(
            self.source / "fidelity.csv",
            FIDELITY_HEADERS,
            [
                ["cTEST000", "XYZ(TESTCUSIP3)", "XYZ CORP", "5", "02/01/2026", "04/15/2026", "$500.00", "$450.00", "$50.00", "$0.00"],
                ["Download generated at", "", "", "", "", "", "", "", "", ""],
            ],
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_normalization_preserves_identifiers_and_reconciles(self) -> None:
        report = normalize_sources(self.source, 2026)
        self.assertEqual(len(report.lots), 3)
        self.assertEqual(report.lots[0].account, "TEST-CHASE")
        self.assertEqual({lot.source_name for lot in report.lots}, {"Chase", "Fidelity"})

    def test_normalization_ignores_generated_output_directories(self) -> None:
        report_copy = self.root / "reports" / "audit" / "copied-chase.csv"
        report_copy.parent.mkdir(parents=True)
        write_csv(report_copy, CHASE_HEADERS, [
            ["Brokerage", "TEST-ARCHIVE", "ARCH", "TESTCUSIP4", "ARCHIVE", "Stock", "1", "01/10/2024", "02/20/2026", "$100.00", "$90.00", "$0.00", "$10.00", "$10.00", "$0.00"],
        ])

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

    def test_dashboard_load_request_renders_report_data(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), InvestmentGainWebApp().handler())
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
        app = InvestmentGainWebApp(
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
        app = InvestmentGainWebApp(
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

        app = InvestmentGainWebApp(
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

    def test_config_editor_fills_missing_defaults_without_overwriting_local_values(self) -> None:
        config_path = self.root / "config.local.json"
        example_path = self.root / "config.example.json"
        config_path.write_text(json.dumps({"ai_provider": "openrouter", "openai_api_key": "existing-secret"}), encoding="utf-8")
        example_path.write_text(json.dumps({"ai_provider": "gemini", "openai_api_key": "", "openai_model": "example-model"}), encoding="utf-8")

        merged = ensure_config_defaults(config_path, example_path)

        self.assertEqual(merged["ai_provider"], "openrouter")
        self.assertEqual(merged["openai_model"], "example-model")
        self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["openai_api_key"], "existing-secret")

    def test_local_settings_modal_keeps_hidden_api_keys_when_left_blank(self) -> None:
        config_path = self.root / "config.local.json"
        config_path.write_text(json.dumps({"openai_api_key": "existing-secret"}), encoding="utf-8")

        save_editable_config({"openai_api_key": [""], "openai_model": ["gpt-test"]}, config_path)
        page = _render_config_modal(editable_config(config_path))

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["openai_api_key"], "existing-secret")
        self.assertEqual(saved["openai_model"], "gpt-test")
        self.assertNotIn("existing-secret", page)
        self.assertIn("Configured — leave blank to keep it", page)

    def test_local_settings_modal_keeps_api_keys_hidden(self) -> None:
        page = _render_config_modal({"ai_provider": "gemini", "filing_status": "head_of_household", "state_residence": "CA", "openai_api_key": "existing-secret"})

        self.assertIn('id="open-local-settings"', page)
        self.assertIn('id="local-settings-dialog"', page)
        self.assertIn('id="local-settings-form"', page)
        self.assertIn('fetch("/settings"', page)
        self.assertIn('<select name="ai_provider">', page)
        self.assertIn('<select name="filing_status">', page)
        self.assertIn('<select name="state_residence">', page)
        self.assertIn('value="gemini" selected', page)
        self.assertIn('value="head_of_household" selected', page)
        self.assertIn('value="CA" selected', page)
        self.assertNotIn("existing-secret", page)

    def test_records_layout_setup_endpoint_returns_source_file_instruction(self) -> None:
        created: list[tuple[Path, int]] = []

        def create_skeleton(parent: Path, year: int) -> Path:
            created.append((parent, year))
            return parent / "Realized Gains"

        app = InvestmentGainWebApp(records_root_skeleton_creator=create_skeleton)
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

        self.assertEqual(from_root, DashboardSelection(newer_source, (records_root / "2026" / "reports").resolve(), 2026))
        self.assertEqual(from_year, DashboardSelection(older_source, (records_root / "2025" / "reports").resolve(), 2025))
        self.assertEqual(from_source, DashboardSelection(newer_source, (records_root / "2026" / "reports").resolve(), 2026))

    def test_selection_keeps_a_direct_csv_folder_for_year_auto_detection(self) -> None:
        selection = selection_from_form({"source": [str(self.source)], "year": [""]})
        self.assertEqual(selection, DashboardSelection(self.source, (self.root / "reports").resolve(), None))

    def test_failed_load_keeps_source_path_and_auto_detect_option_visible(self) -> None:
        source = self.root / "missing-source"
        page = _render_dashboard(DashboardSelection(source, self.root / "reports", None), error="Input directory does not exist")
        self.assertIn(f'value="{source}"', page)
        self.assertIn('value="" selected>Auto-detect</option>', page)
        self.assertIn('formaction="/open-realized-gains-root"', page)
        self.assertIn('formtarget="finder-result"', page)
        self.assertIn('action="/setup-realized-gains-root"', page)
        self.assertIn('id="setup-realized-gains-form"', page)
        self.assertIn('Create a standard Realized Gains folder here?', page)
        self.assertIn('button.textContent="Set up folders"', page)
        self.assertIn('class="load-data-form"', page)
        self.assertIn('class="source-folder-row"', page)
        self.assertIn('>Choose folder</button>', page)
        self.assertIn('id="source-folder-path"', page)
        self.assertIn('action="/dashboard"', page)
        self.assertIn('>Load data</button>', page)

    def test_gemini_provider_response_preserves_json_text(self) -> None:
        guidance = parse_gemini_response({
            "candidates": [{
                "content": {"parts": [{"text": "Federal gains are subject to different rates."}]},
                "groundingMetadata": {"groundingChunks": [{"web": {"title": "IRS", "uri": "https://www.irs.gov"}}]},
            }],
        })
        self.assertIn("Federal gains", guidance)
        self.assertNotIn("Sources:", guidance)

    def test_openrouter_provider_response_preserves_json_text(self) -> None:
        guidance = parse_openrouter_response({
            "choices": [{"message": {
                "content": "California taxes capital gains as ordinary income.",
                "annotations": [{"url_citation": {"title": "FTB", "url": "https://www.ftb.ca.gov"}}],
            }}],
        })
        self.assertIn("California taxes", guidance)
        self.assertNotIn("Sources:", guidance)

    def test_guidance_prompt_requests_valid_bracket_json(self) -> None:
        prompt = TaxGuidancePromptBuilder().build(2026, "California", TaxAssumptions(state_code="CA"))
        self.assertIn('"breakdowns"', prompt)
        self.assertIn('"brackets"', prompt)
        self.assertIn('"type":"federal_ordinary"', prompt)
        self.assertIn('"standard_deduction"', prompt)
        self.assertIn("federal_ordinary, federal_long_term, or state", prompt)
        self.assertIn("Reply with valid JSON only", prompt)

    def test_guidance_service_delegates_to_selected_provider(self) -> None:
        class StubProvider:
            provider_id = "openai"

            def __init__(self) -> None:
                self.prompt = ""

            def request(self, prompt: str) -> str:
                self.prompt = prompt
                return "guidance"

        provider = StubProvider()
        guidance = TaxGuidanceService((provider,)).request(2026, TaxAssumptions(state_code="CA", ai_provider="openai"))
        self.assertEqual(guidance, "guidance")
        self.assertIn("California (CA)", provider.prompt)

    def test_bracket_mapper_selects_rates_for_taxable_income(self) -> None:
        response = {
            "breakdowns": [
                {"type": "federal_short_term", "brackets": [{"bracket": 50000, "rate": 12}, {"bracket": None, "rate": 22}]},
                {"type": "federal_long_term", "brackets": [{"bracket": 50000, "rate": 0}, {"bracket": None, "rate": 15}]},
                {"type": "state", "brackets": [{"bracket": 70000, "rate": 5}, {"bracket": None, "rate": 8}]},
            ]
        }
        mapping = map_bracket_rates(response, Decimal("60000"))
        self.assertEqual(mapping.federal_short_term.rate, Decimal("0.22"))
        self.assertEqual(mapping.federal_long_term.rate, Decimal("0.15"))
        self.assertEqual(mapping.state.rate, Decimal("0.05"))

    def test_guidance_brackets_calculate_each_gain_type_incrementally(self) -> None:
        report = normalize_sources(self.source, 2026)
        response = self._valid_guidance_response()
        assumptions = TaxAssumptions(state_code="CA", other_ordinary_taxable_income=Decimal("84980"))
        estimate = estimate_taxes(report, assumptions, response)
        rates = map_gain_rates(response, Decimal("84980"), Decimal("50"), Decimal("100"))
        self.assertEqual(estimate.federal_short_term, Decimal("11.0"))
        self.assertEqual(estimate.federal_long_term, Decimal("0"))
        self.assertEqual(estimate.state, Decimal("11.4"))
        self.assertEqual(rates.federal_short_term.rate, Decimal("0.22"))
        self.assertEqual(rates.federal_long_term.rate, Decimal("0"))
        self.assertEqual(rates.state.rate, Decimal("0.08"))
        formula = build_tax_formula(response, Decimal("84980"), Decimal("50"), Decimal("100"))
        self.assertEqual(formula.federal_short_term.opening_income, Decimal("69980"))
        self.assertEqual(formula.federal_short_term.closing_income, Decimal("70030"))
        self.assertEqual(formula.state.components[0].taxable_amount, Decimal("130"))
        self.assertEqual(formula.state.components[0].rate, Decimal("0.08"))
        self.assertEqual(formula.state.components[1].taxable_amount, Decimal("20"))
        self.assertEqual(formula.state.components[1].rate, Decimal("0.05"))
        self.assertEqual(sum(component.taxable_amount for component in formula.state.total_components), formula.state.closing_income)
        self.assertEqual(formula.estimate, estimate)
        remaining_deduction_formula = build_tax_formula(response, Decimal("10000"), Decimal("50"), Decimal("6000"))
        self.assertEqual(remaining_deduction_formula.remaining_standard_deduction, Decimal("4950"))
        self.assertEqual(remaining_deduction_formula.federal_long_term.closing_income, Decimal("1050"))

    def test_payment_website_uses_reference_mapping(self) -> None:
        california = payment_website("CA")
        self.assertIsNotNone(california)
        self.assertEqual(california.url, "https://www.ftb.ca.gov/pay/index.html")
        self.assertEqual(payment_website("TX"), None)

    def test_tax_inputs_persist_without_replacing_other_local_settings(self) -> None:
        config_path = self.root / "config.local.json"
        config_path.write_text(json.dumps({"openai_api_key": "preserved", "ai_provider": "gemini"}), encoding="utf-8")
        save_tax_input_defaults(
            {
                "state": ["ca"],
                "other_ordinary_taxable_income": ["12,345.67"],
                "filing_status": ["head_of_household"],
                "num_dependents": ["2"],
                "ai_provider": ["openrouter"],
            },
            config_path,
        )
        self.assertEqual(tax_input_defaults(config_path), ("CA", "12345.67"))
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["openai_api_key"], "preserved")
        self.assertEqual(saved["ai_provider"], "openrouter")
        self.assertEqual(saved["filing_status"], "head_of_household")
        self.assertEqual(saved["num_dependents"], 2)

    def test_records_root_persists_without_replacing_other_local_settings(self) -> None:
        config_path = self.root / "config.local.json"
        config_path.write_text(json.dumps({"openai_api_key": "preserved", "ai_provider": "gemini"}), encoding="utf-8")
        parent = self.root / "Investments"
        records_root = parent / "Realized Gains"
        records_root.mkdir(parents=True)

        save_realized_gains_root(parent, config_path)

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["realized_gains_root"], str(records_root.resolve()))
        self.assertEqual(saved["openai_api_key"], "preserved")
        self.assertEqual(saved["ai_provider"], "gemini")

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

    def test_guidance_response_is_saved_beneath_report_folder(self) -> None:
        response = self._valid_guidance_response()
        store = GuidanceResponseStore()
        profile = GuidanceProfile("CA", "single", 0, "gemini")
        paths = store.save(self.root / "reports", 2026, profile, [response, response, response], 1)
        self.assertEqual(paths[1], self.root / "reports" / "ai-rate-guidance" / "2026-gemini-ca-single-0-response-2-selected.yaml")
        self.assertTrue(all(path.is_file() for path in paths))
        self.assertIn("selected: true", paths[1].read_text(encoding="utf-8"))
        self.assertIn("state_code: CA", paths[1].read_text(encoding="utf-8"))
        self.assertEqual(len(store.load_all(self.root / "reports", 2026, profile)), 3)
        self.assertEqual(store.load_all(self.root / "reports", 2026, GuidanceProfile("NY", "single", 0, "gemini")), ())
        selected = store.load_selected(self.root / "reports", 2026, profile)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.path, paths[1])
        self.assertEqual(selected.response, validate_guidance_response(response))

    def test_guidance_response_store_preserves_user_edits(self) -> None:
        response = self._valid_guidance_response()
        response["breakdowns"][0]["brackets"].insert(1, {"bracket": 75000, "rate": 18})
        response["breakdowns"][1]["brackets"][1]["rate"] = 20
        response["standard_deduction"]["amount"] = 18000
        store = GuidanceResponseStore()
        profile = GuidanceProfile("CA", "single", 0, "gemini")

        path = store.save(self.root / "reports", 2026, profile, [response], 0)[0]

        saved = yaml.safe_load(path.read_text(encoding="utf-8"))["response"]
        self.assertEqual(saved["breakdowns"][0]["brackets"][1], {"bracket": 75000.0, "rate": 18.0})
        self.assertEqual(saved["breakdowns"][1]["brackets"][1]["rate"], 20.0)
        self.assertEqual(saved["standard_deduction"]["amount"], 18000.0)

    def test_legacy_guidance_is_available_for_the_matching_provider_and_year(self) -> None:
        response = self._valid_guidance_response()
        directory = self.root / "reports" / "ai-rate-guidance"
        directory.mkdir(parents=True)
        legacy_path = directory / "2026-openrouter-response-1-selected.yaml"
        legacy_path.write_text(
            yaml.safe_dump({"provider": "openrouter", "report_year": 2026, "selected": True, "response": response}),
            encoding="utf-8",
        )
        store = GuidanceResponseStore()
        profile = GuidanceProfile("CA", "head_of_household", 2, "openrouter")

        selected = store.load_selected(self.root / "reports", 2026, profile)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.path, legacy_path)
        self.assertEqual(selected.profile, profile)
        self.assertIsNone(store.load_selected(self.root / "reports", 2026, GuidanceProfile("CA", "single", 0, "gemini")))

    def test_guidance_validator_rejects_missing_standard_deduction(self) -> None:
        response = self._valid_guidance_response()
        del response["standard_deduction"]
        with self.assertRaisesRegex(Exception, "standard_deduction"):
            validate_guidance_response(response)

    def test_guidance_validator_checks_requested_filing_status(self) -> None:
        with self.assertRaisesRegex(Exception, "requested head_of_household"):
            validate_guidance_response(self._valid_guidance_response(), "head_of_household")

    def test_review_service_validates_provider_candidate(self) -> None:
        response = self._valid_guidance_response()
        service = GuidanceReviewService(request_guidance=lambda _year, _assumptions: json.dumps(response))
        candidate = service.request_candidate(2026, TaxAssumptions(state_code="CA"))
        self.assertEqual(candidate, validate_guidance_response(response, "single"))

    def test_tax_panel_includes_selectable_ai_providers(self) -> None:
        report = normalize_sources(self.source, 2026)
        selection = DashboardSelection(self.source, self.root / "reports", 2026)
        page = _render_tax_section(report, selection, TaxAssumptions(state_code="CA", ai_provider="gemini"))
        self.assertIn('id="ai-provider"', page)
        self.assertIn("Google Gemini API", page)
        self.assertIn("OpenRouter API", page)
        self.assertIn('name="ai_provider"', page)
        self.assertIn('name="other_ordinary_taxable_income"', page)
        self.assertIn('id="guidance-ordinary-income"', page)
        self.assertNotIn('name="taxable_income"', page)
        self.assertLess(page.index('id="ai-provider"'), page.index('id="guidance-button"'))
        self.assertIn('const syncProfileControls =', page)
        self.assertIn('Get Google Gemini API rate guidance', page)
        self.assertIn('id="guidance-dialog"', page)
        self.assertIn('id="switch-guidance-button"', page)
        self.assertIn('No saved ${activeProviderLabel()} responses', page)
        self.assertIn('Review or switch ${count} saved ${activeProviderLabel()} response', page)
        self.assertIn('Tax profile changed. Review matching saved guidance', page)
        self.assertIn('new AbortController()', page)
        self.assertIn('5 - saved.responses.length', page)
        self.assertIn('retry.disabled = false', page)
        self.assertIn('await post("/guidance-save"', page)
        self.assertIn('window.location.assign(dashboardUrl())', page)
        self.assertIn('Add bracket', page)
        self.assertIn('remove-bracket', page)
        self.assertIn('deductionAmount.addEventListener', page)
        self.assertIn('Federal ordinary income', page)
        self.assertIn('Federal long-term gains', page)
        self.assertIn('State income tax', page)
        self.assertIn('https://www.irs.gov/payments', page)
        guided_page = _render_tax_section(
            report,
            selection,
            TaxAssumptions(state_code="CA", ai_provider="gemini", other_ordinary_taxable_income=Decimal("20000")),
            self._valid_guidance_response(),
        )
        self.assertIn('Tax from this type:', guided_page)
        self.assertIn('Federal ordinary / short-term rate', guided_page)
        self.assertIn('Pay California estimated tax', guided_page)
        self.assertIn('See exact formula', guided_page)
        self.assertIn('Exact tax formula', guided_page)
        self.assertIn('class="tax-workflow-actions"', guided_page)
        self.assertIn('class="tax-formula-summary"', guided_page)
        self.assertIn('.tax-formula-summary .formula-action', guided_page)
        self.assertIn('highest rate down', guided_page)

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

    def test_existing_report_requires_overwrite(self) -> None:
        output_dir = self.root / "reports"
        generate_report(self.source, year=2026, output_dir=output_dir)
        with self.assertRaisesRegex(Exception, "already exists"):
            generate_report(self.source, year=2026, output_dir=output_dir)

    @staticmethod
    def _valid_guidance_response() -> dict[str, object]:
        return {
            "breakdowns": [
                {"type": "federal_ordinary", "brackets": [{"bracket": 50000, "rate": 12}, {"bracket": None, "rate": 22}]},
                {"type": "federal_long_term", "brackets": [{"bracket": 50000, "rate": 0}, {"bracket": None, "rate": 15}]},
                {"type": "state", "brackets": [{"bracket": 70000, "rate": 5}, {"bracket": None, "rate": 8}]},
            ],
            "standard_deduction": {"filing_status": "single", "amount": 15000},
            "sources": [],
        }


if __name__ == "__main__":
    unittest.main()
