"""Local, user-specific application settings."""

from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent
LOCAL_CONFIG_PATH = APP_DIR / "config.local.json"
REALIZED_GAINS_FOLDER_NAME = "Realized Gains"


def _local_config(config_path: Path = LOCAL_CONFIG_PATH) -> dict[str, object]:
    """Load ignored, user-specific settings without exposing their values."""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return config if isinstance(config, dict) else {}


def realized_gains_root(config_path: Path = LOCAL_CONFIG_PATH) -> Path | None:
    """Return the configured records root, if a valid local setting exists."""
    config = _local_config(config_path)
    value = config.get("realized_gains_root")
    return Path(value).expanduser() if isinstance(value, str) and value.strip() else None


def save_realized_gains_root(root: Path, config_path: Path = LOCAL_CONFIG_PATH) -> Path:
    """Persist one Finder-selected records root without replacing other local settings."""
    records_root = _resolve_realized_gains_root(root)
    config = _local_config(config_path)
    config["realized_gains_root"] = str(records_root)
    _write_local_config(config, config_path)
    return records_root


def create_realized_gains_skeleton(parent_folder: Path, year: int, config_path: Path = LOCAL_CONFIG_PATH) -> Path:
    """Create the standard records layout beneath a user-selected parent folder."""
    parent_folder = parent_folder.expanduser().resolve()
    if not parent_folder.is_dir():
        raise ValueError("Choose an existing folder before setting up the records layout.")
    if not 1900 <= year <= 2200:
        raise ValueError("Choose a valid sale year before setting up the records layout.")
    records_root = parent_folder / REALIZED_GAINS_FOLDER_NAME
    (records_root / str(year) / "source").mkdir(parents=True, exist_ok=True)
    (records_root / str(year) / "reports").mkdir(parents=True, exist_ok=True)
    return save_realized_gains_root(records_root, config_path)


def _resolve_realized_gains_root(selected_folder: Path) -> Path:
    """Resolve a selected records folder to a directory named Realized Gains."""
    selected_folder = selected_folder.expanduser().resolve()
    if not selected_folder.is_dir():
        raise ValueError("Choose an existing Realized Gains folder or its parent folder.")
    if selected_folder.name.casefold() == REALIZED_GAINS_FOLDER_NAME.casefold():
        return selected_folder
    records_root = selected_folder / REALIZED_GAINS_FOLDER_NAME
    if records_root.is_dir():
        return records_root
    raise ValueError("The selected folder does not contain a Realized Gains folder.")


def openai_api_key(config_path: Path = LOCAL_CONFIG_PATH) -> str | None:
    """Return the optional API key stored only in the ignored local config file."""
    config = _local_config(config_path)
    value = config.get("openai_api_key")
    return value.strip() if isinstance(value, str) and value.strip() else None


def gemini_api_key(config_path: Path = LOCAL_CONFIG_PATH) -> str | None:
    """Return the optional Gemini API key stored in local configuration only."""
    value = _local_config(config_path).get("gemini_api_key")
    return value.strip() if isinstance(value, str) and value.strip() else None


def openrouter_api_key(config_path: Path = LOCAL_CONFIG_PATH) -> str | None:
    """Return the optional OpenRouter API key stored in local configuration only."""
    value = _local_config(config_path).get("openrouter_api_key")
    return value.strip() if isinstance(value, str) and value.strip() else None


def guidance_provider(config_path: Path = LOCAL_CONFIG_PATH) -> str:
    """Return the configured guidance provider, defaulting to OpenAI."""
    value = _local_config(config_path).get("ai_provider")
    return value.strip().lower() if isinstance(value, str) and value.strip() else "openai"


def openai_model(config_path: Path = LOCAL_CONFIG_PATH) -> str:
    """Return the configured OpenAI model for tax-rate research."""
    value = _local_config(config_path).get("openai_model")
    return value.strip() if isinstance(value, str) and value.strip() else "gpt-5.6"


def gemini_model(config_path: Path = LOCAL_CONFIG_PATH) -> str:
    """Return the configured Gemini model for tax-rate research."""
    value = _local_config(config_path).get("gemini_model")
    return value.strip() if isinstance(value, str) and value.strip() else "gemini-3.7-flash"


def openrouter_model(config_path: Path = LOCAL_CONFIG_PATH) -> str:
    """Return the OpenRouter model or router selected for tax-rate research."""
    value = _local_config(config_path).get("openrouter_model")
    return value.strip() if isinstance(value, str) and value.strip() else "openai/gpt-4o"


def tax_defaults(config_path: Path = LOCAL_CONFIG_PATH) -> tuple[str, int]:
    """Return filing status and dependent count from the ignored local config."""
    config = _local_config(config_path)
    status = config.get("filing_status")
    filing_status = status.strip() if isinstance(status, str) and status.strip() else "single"
    try:
        dependents = max(0, int(config.get("num_dependents", 0)))
    except (TypeError, ValueError):
        dependents = 0
    return filing_status, dependents


def tax_input_defaults(config_path: Path = LOCAL_CONFIG_PATH) -> tuple[str, str]:
    """Return the last selected state and ordinary income for initial rendering."""
    config = _local_config(config_path)
    state = config.get("state_residence")
    income = config.get("other_ordinary_taxable_income")
    return (
        state.strip().upper() if isinstance(state, str) else "",
        income.strip() if isinstance(income, str) else "0",
    )


def save_tax_input_defaults(values: dict[str, list[str]], config_path: Path = LOCAL_CONFIG_PATH) -> None:
    """Persist valid tax-pane inputs without exposing or replacing API credentials."""
    if "state" not in values and "other_ordinary_taxable_income" not in values:
        return
    state = values.get("state", [""])[0].strip().upper()
    income = _non_negative_currency(values.get("other_ordinary_taxable_income", ["0"])[0])
    config = _local_config(config_path)
    config["state_residence"] = state
    config["other_ordinary_taxable_income"] = income
    _write_local_config(config, config_path)


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
    return tuple(sorted(
        int(path.name)
        for path in root.iterdir()
        if path.is_dir() and path.name.isdigit() and 1900 <= int(path.name) <= 2200
    ))
