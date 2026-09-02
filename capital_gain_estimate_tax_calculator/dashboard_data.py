"""Application service for loading the data shown by the dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from .dashboard_selection import DashboardSelection
from .models import NormalizedReport
from .normalizer import normalize_sources


@dataclass(frozen=True)
class DashboardData:
    """A normalized report paired with the selection resolved from its data."""

    selection: DashboardSelection
    report: NormalizedReport


class DashboardDataLoader:
    """Load dashboard data behind a focused, replaceable application boundary."""

    def load(self, selection: DashboardSelection) -> DashboardData:
        report = normalize_sources(selection.source_dir, selection.year)
        return DashboardData(selection.with_year(report.report_year), report)


def load_dashboard_data(selection: DashboardSelection) -> DashboardData:
    """Load data through the default dashboard-data service."""
    return DashboardDataLoader().load(selection)
