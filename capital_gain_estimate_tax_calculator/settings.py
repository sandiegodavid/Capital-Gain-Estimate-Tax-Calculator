"""Local, user-specific application settings."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .interfaces import SettingsRepository
from .records_layout import create_realized_gains_layout, resolve_realized_gains_root

APP_DIR = Path(__file__).resolve().parent.parent
LOCAL_CONFIG_PATH = APP_DIR / "config.local.json"
EXAMPLE_CONFIG_PATH = APP_DIR / "config.example.json"
EXAMPLE_RECORDS_ROOT = "/path/to/Financial Records/Investments/Realized Gains"


@dataclass(frozen=True)
class JsonSettingsRepository:
    """Atomic JSON adapter; domain and application code never handle JSON directly."""

    path: Path = LOCAL_CONFIG_PATH

    def load(self) -> dict[str, object]:
        return _read_json_object(self.path)

    def save(self, value: dict[str, object]) -> None:
        _write_local_config(value, self.path)


@dataclass(frozen=True)
class TaxProfileDefaults:
    """Saved tax-profile values, independent of JSON storage details."""

    state_code: str = ""
    other_ordinary_taxable_income: str = "0"
    filing_status: str = "single"
    qualified_children: int = 0
    other_dependents: int = 0
    short_term_carryover_loss: str = "0"
    long_term_carryover_loss: str = "0"
    state_eligible_dependents_by_state: Mapping[str, int] = field(default_factory=dict)

    def state_eligible_dependents(self, state_code: str) -> int | None:
        return self.state_eligible_dependents_by_state.get(state_code.upper())


@dataclass(frozen=True)
class RecordsConfiguration:
    """Saved records-folder setting used by the dashboard."""

    realized_gains_root: Path | None = None


@dataclass(frozen=True)
class AppSettings:
    """Typed settings boundary that preserves unknown local configuration keys."""

    tax_profile: TaxProfileDefaults = field(default_factory=TaxProfileDefaults)
    records: RecordsConfiguration = field(default_factory=RecordsConfiguration)
    additional_values: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "AppSettings":
        state = value.get("state_residence")
        income = value.get("other_ordinary_taxable_income")
        status = value.get("filing_status")
        saved_counts = value.get("state_eligible_dependents_by_state")
        counts = (
            {
                code.upper(): max(0, int(count))
                for code, count in saved_counts.items()
                if isinstance(code, str) and _is_non_negative_integer(count)
            }
            if isinstance(saved_counts, Mapping)
            else {}
        )
        root = value.get("realized_gains_root")
        known_keys = {
            "state_residence",
            "other_ordinary_taxable_income",
            "filing_status",
            "qualified_children",
            "other_dependents",
            "num_dependents",
            "short_term_carryover_loss",
            "long_term_carryover_loss",
            "state_eligible_dependents_by_state",
            "realized_gains_root",
        }
        return cls(
            tax_profile=TaxProfileDefaults(
                state_code=state.strip().upper() if isinstance(state, str) else "",
                other_ordinary_taxable_income=income.strip() if isinstance(income, str) else "0",
                filing_status=status.strip() if isinstance(status, str) and status.strip() else "single",
                qualified_children=_non_negative_count(value.get("qualified_children", 0)),
                other_dependents=_non_negative_count(value.get("other_dependents", value.get("num_dependents", 0))),
                short_term_carryover_loss=str(value.get("short_term_carryover_loss", "0")),
                long_term_carryover_loss=str(value.get("long_term_carryover_loss", "0")),
                state_eligible_dependents_by_state=counts,
            ),
            records=RecordsConfiguration(_records_root(root)),
            additional_values={key: item for key, item in value.items() if key not in known_keys},
        )

    def to_mapping(self) -> dict[str, object]:
        profile = self.tax_profile
        result = dict(self.additional_values)
        result.update(
            {
                "state_residence": profile.state_code,
                "other_ordinary_taxable_income": profile.other_ordinary_taxable_income,
                "filing_status": profile.filing_status,
                "qualified_children": profile.qualified_children,
                "other_dependents": profile.other_dependents,
                "short_term_carryover_loss": profile.short_term_carryover_loss,
                "long_term_carryover_loss": profile.long_term_carryover_loss,
                "state_eligible_dependents_by_state": dict(profile.state_eligible_dependents_by_state),
            }
        )
        if self.records.realized_gains_root is not None:
            result["realized_gains_root"] = str(self.records.realized_gains_root)
        return result


@dataclass(frozen=True)
class SettingsService:
    """Coordinates typed settings reads and updates through a narrow repository."""

    repository: SettingsRepository

    @classmethod
    def default(cls) -> "SettingsService":
        return cls(JsonSettingsRepository())

    def load(self) -> AppSettings:
        return AppSettings.from_mapping(self.repository.load())

    def ensure_defaults(self, defaults: Mapping[str, object]) -> AppSettings:
        current = self.repository.load()
        merged = {**defaults, **current}
        if merged != current:
            self.repository.save(merged)
        return AppSettings.from_mapping(merged)

    def save_records_root(self, root: Path) -> Path:
        records_root = resolve_realized_gains_root(root)
        settings = self.load()
        self.repository.save(
            AppSettings(
                settings.tax_profile, RecordsConfiguration(records_root), settings.additional_values
            ).to_mapping()
        )
        return records_root

    def save_tax_profile(self, values: Mapping[str, list[str]]) -> None:
        profile_keys = {
            "state",
            "other_ordinary_taxable_income",
            "short_term_carryover_loss",
            "long_term_carryover_loss",
            "filing_status",
            "qualified_children",
            "other_dependents",
            "state_eligible_dependents",
        }
        if not profile_keys.intersection(values):
            return
        existing = self.load()
        profile = existing.tax_profile
        state = _form_value(values, "state", profile.state_code).strip().upper()
        counts = dict(profile.state_eligible_dependents_by_state)
        if "state_eligible_dependents" in values:
            count = _parse_non_negative_count(_form_value(values, "state_eligible_dependents"))
            if state and count is not None:
                counts[state] = count
            elif state:
                counts.pop(state, None)
        updated = TaxProfileDefaults(
            state_code=state,
            other_ordinary_taxable_income=_non_negative_currency(
                _form_value(values, "other_ordinary_taxable_income", "0")
            ),
            filing_status=_form_value(values, "filing_status", profile.filing_status).strip(),
            qualified_children=_updated_count(values, "qualified_children", profile.qualified_children),
            other_dependents=_updated_count(values, "other_dependents", profile.other_dependents),
            short_term_carryover_loss=_non_negative_currency(_form_value(values, "short_term_carryover_loss", "0")),
            long_term_carryover_loss=_non_negative_currency(_form_value(values, "long_term_carryover_loss", "0")),
            state_eligible_dependents_by_state=counts,
        )
        self.repository.save(AppSettings(updated, existing.records, existing.additional_values).to_mapping())


def _read_json_object(config_path: Path) -> dict[str, object]:
    """Load ignored, user-specific settings without exposing their values."""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return config if isinstance(config, dict) else {}


def _records_root(value: object) -> Path | None:
    """Accept only an explicitly configured records root, never the old example value."""
    if not isinstance(value, str) or not value.strip() or value.strip() == EXAMPLE_RECORDS_ROOT:
        return None
    return Path(value).expanduser()


def ensure_config_defaults(
    config_path: Path = LOCAL_CONFIG_PATH,
    example_path: Path = EXAMPLE_CONFIG_PATH,
) -> dict[str, object]:
    """Fill missing local settings without treating an example folder as user data."""
    defaults = JsonSettingsRepository(example_path).load()
    defaults.pop("realized_gains_root", None)
    return SettingsService(JsonSettingsRepository(config_path)).ensure_defaults(defaults).to_mapping()


def realized_gains_root(config_path: Path = LOCAL_CONFIG_PATH) -> Path | None:
    """Return the configured records root, if a valid local setting exists."""
    return SettingsService(JsonSettingsRepository(config_path)).load().records.realized_gains_root


def save_realized_gains_root(root: Path, config_path: Path = LOCAL_CONFIG_PATH) -> Path:
    """Persist one Finder-selected records root without replacing other local settings."""
    return SettingsService(JsonSettingsRepository(config_path)).save_records_root(root)


def create_realized_gains_skeleton(parent_folder: Path, year: int, config_path: Path = LOCAL_CONFIG_PATH) -> Path:
    """Create the standard records layout beneath a user-selected parent folder."""
    records_root = create_realized_gains_layout(parent_folder, year)
    return save_realized_gains_root(records_root, config_path)


def tax_defaults(config_path: Path = LOCAL_CONFIG_PATH) -> tuple[str, int, int]:
    """Return filing status and the two dependent counts from local config."""
    profile = SettingsService(JsonSettingsRepository(config_path)).load().tax_profile
    return profile.filing_status, profile.qualified_children, profile.other_dependents


def tax_input_defaults(config_path: Path = LOCAL_CONFIG_PATH) -> tuple[str, str]:
    """Return the last selected state and ordinary income for initial rendering."""
    profile = SettingsService(JsonSettingsRepository(config_path)).load().tax_profile
    return profile.state_code, profile.other_ordinary_taxable_income


def state_eligible_dependents_default(state_code: str, config_path: Path = LOCAL_CONFIG_PATH) -> int | None:
    """Return the separately confirmed state-dependent count, if one was saved."""
    return SettingsService(JsonSettingsRepository(config_path)).load().tax_profile.state_eligible_dependents(state_code)


def carryover_loss_defaults(config_path: Path = LOCAL_CONFIG_PATH) -> tuple[str, str]:
    """Return persisted short- and long-term capital-loss carryovers."""
    profile = SettingsService(JsonSettingsRepository(config_path)).load().tax_profile
    return profile.short_term_carryover_loss, profile.long_term_carryover_loss


def save_tax_input_defaults(values: dict[str, list[str]], config_path: Path = LOCAL_CONFIG_PATH) -> None:
    """Persist tax-profile inputs without replacing unrelated local settings."""
    SettingsService(JsonSettingsRepository(config_path)).save_tax_profile(values)


def _form_value(values: Mapping[str, list[str]], name: str, default: str = "") -> str:
    submitted = values.get(name)
    return submitted[0] if submitted else default


def _parse_non_negative_count(value: object) -> int | None:
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _updated_count(values: Mapping[str, list[str]], name: str, existing: int) -> int:
    if name not in values:
        return existing
    parsed = _parse_non_negative_count(_form_value(values, name))
    return existing if parsed is None else parsed


def _non_negative_count(value: object) -> int:
    return _parse_non_negative_count(value) or 0


def _is_non_negative_integer(value: object) -> bool:
    return _parse_non_negative_count(value) is not None


def _non_negative_currency(value: object) -> str:
    try:
        return f"{max(Decimal('0'), Decimal(str(value).replace(',', '').replace('$', '').strip() or '0')):f}"
    except (InvalidOperation, ValueError):
        return "0"


def _write_local_config(config: dict[str, object], config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{config_path.stem}-", suffix=".tmp", dir=config_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")
        os.replace(temporary_name, config_path)
    finally:
        if Path(temporary_name).exists():
            Path(temporary_name).unlink()


def available_report_years(root: Path | None) -> tuple[int, ...]:
    """Return valid year folders directly beneath the configured records root."""
    if root is None or not root.is_dir():
        return ()
    return tuple(
        sorted(
            int(path.name)
            for path in root.iterdir()
            if path.is_dir() and path.name.isdigit() and 1900 <= int(path.name) <= 2200
        )
    )
