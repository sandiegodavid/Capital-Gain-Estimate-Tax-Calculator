"""Application-facing actions for dashboard and report HTTP endpoints."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path

from .dashboard_data import DashboardData, load_dashboard_data
from .dashboard_selection import DashboardSelection, selection_from_form
from .models import ReportError
from .service import generate_report
from .settings import SettingsService
from .tax_estimate import TaxAssumptions, assumptions_from_form
from .web_http import FormValues

DashboardRenderer = Callable[
    [DashboardSelection | None, TaxAssumptions | None, str, str, bool, DashboardData | None], str
]
DashboardLoader = Callable[[DashboardSelection], DashboardData]
ReportGenerator = Callable[..., tuple[Path, dict[str, object]]]
SelectionParser = Callable[[FormValues], DashboardSelection | None]


@dataclass(frozen=True)
class PageResult:
    page: str
    status: HTTPStatus = HTTPStatus.OK
    generated_report: Path | None = None


@dataclass(frozen=True)
class DashboardActions:
    settings: SettingsService
    renderer: DashboardRenderer
    dashboard_loader: DashboardLoader = load_dashboard_data
    report_generator: ReportGenerator = generate_report
    selection_parser: SelectionParser = selection_from_form

    def load(self, form: FormValues) -> PageResult:
        self.settings.save_tax_profile(form)
        selection = self.selection_parser(form)
        assumptions = assumptions_from_form(form, self.settings.load().tax_profile)
        try:
            if selection is None:
                return PageResult(self.renderer(None, assumptions, "", "", False, None))
            data = self.dashboard_loader(selection)
            return PageResult(self.renderer(data.selection, assumptions, "", "", False, data))
        except (ReportError, OSError) as exc:
            return PageResult(self.renderer(selection, assumptions, "", str(exc), False, None), HTTPStatus.BAD_REQUEST)

    def generate(self, form: FormValues) -> PageResult:
        self.settings.save_tax_profile(form)
        selection = self.selection_parser(form)
        if selection is None:
            return PageResult(
                self.renderer(None, None, "", "Choose a valid sale year and source folder.", False, None),
                HTTPStatus.BAD_REQUEST,
            )
        try:
            report_path, _ = self.report_generator(
                selection.source_dir,
                selection.year,
                selection.output_dir,
                overwrite="overwrite" in form,
                keep_audit_files="audit" in form,
                included_source_files=selection.included_source_files,
            )
            assumptions = assumptions_from_form({}, self.settings.load().tax_profile)
            return PageResult(
                self.renderer(
                    selection,
                    assumptions,
                    f"Created {report_path.name}. Download it from this browser session.",
                    "",
                    True,
                    None,
                ),
                generated_report=report_path,
            )
        except (ReportError, OSError) as exc:
            return PageResult(self.renderer(selection, None, "", str(exc), False, None), HTTPStatus.BAD_REQUEST)
