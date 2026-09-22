"""Production composition root for the local dashboard application."""

from __future__ import annotations

from .application import EstimateTaxes
from .finder import choose_folder_in_finder
from .settings import (
    SettingsService,
    create_realized_gains_skeleton,
    realized_gains_root,
    save_realized_gains_root,
)
from .tax_rules import TaxRuleStore
from .web import InvestmentGainWebApp


def create_web_application() -> InvestmentGainWebApp:
    """Wire concrete infrastructure adapters for the desktop HTTP boundary."""
    return InvestmentGainWebApp(
        records_root_saver=save_realized_gains_root,
        finder_folder_chooser=choose_folder_in_finder,
        records_root_skeleton_creator=create_realized_gains_skeleton,
        records_root_provider=realized_gains_root,
        settings_service=SettingsService.default(),
        tax_estimator=EstimateTaxes(TaxRuleStore()),
    )
