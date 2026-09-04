"""Local, user-specific application settings."""

from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .records_layout import create_realized_gains_layout, resolve_realized_gains_root

APP_DIR = Path(__file__).resolve().parent.parent
LOCAL_CONFIG_PATH = APP_DIR / "config.local.json"
EXAMPLE_CONFIG_PATH = APP_DIR / "config.example.json"
SENSITIVE_CONFIG_KEYS = frozenset({"openai_api_key", "gemini_api_key", "openrouter_api_key"})
EDITABLE_CONFIG_KEYS = (
    "realized_gains_root",
    "ai_provider",
    "openai_api_key",
    "openai_model",
    "gemini_api_key",
    "gemini_model",
    "openrouter_api_key",
    "openrouter_model",
    "filing_status",
    "num_dependents",
    "state_residence",
    "other_ordinary_taxable_income",
    "short_term_carryover_loss",
    "long_term_carryover_loss",
)


def _local_config(config_path: Path = LOCAL_CONFIG_PATH) -> dict[str, object]:
    """Load ignored, user-specific settings without exposing their values."""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return config if isinstance(config, dict) else {}


def ensure_config_defaults(
    config_path: Path = LOCAL_CONFIG_PATH,
    example_path: Path = EXAMPLE_CONFIG_PATH,
) -> dict[str, object]:
    """Fill missing local settings from the safe, versioned example configuration."""
    config = _local_config(config_path)
    defaults = _local_config(example_path)
    merged = {**defaults, **config}
    if merged != config:
        _write_local_config(merged, config_path)
    return merged


def editable_config(config_path: Path = LOCAL_CONFIG_PATH) -> dict[str, object]:
    """Return local settings for the browser editor, retaining secret values locally."""
    config = ensure_config_defaults(config_path)
    return {key: config.get(key, "") for key in EDITABLE_CONFIG_KEYS}


def save_editable_config(values: dict[str, list[str]], config_path: Path = LOCAL_CONFIG_PATH) -> None:
    """Persist browser-edited settings without clearing an existing API key accidentally."""
    config = ensure_config_defaults(config_path)
    for key in EDITABLE_CONFIG_KEYS:
        if key not in values:
            continue
        value = values[key][0].strip()
        if key in SENSITIVE_CONFIG_KEYS and not value:
            continue
        config[key] = value
    _write_local_config(config, config_path)


def realized_gains_root(config_path: Path = LOCAL_CONFIG_PATH) -> Path | None:
    """Return the configured records root, if a valid local setting exists."""
    config = _local_config(config_path)
    value = config.get("realized_gains_root")
    return Path(value).expanduser() if isinstance(value, str) and value.strip() else None


def save_realized_gains_root(root: Path, config_path: Path = LOCAL_CONFIG_PATH) -> Path:
    """Persist one Finder-selected records root without replacing other local settings."""
    records_root = resolve_realized_gains_root(root)
    config = _local_config(config_path)
    config["realized_gains_root"] = str(records_root)
    _write_local_config(config, config_path)
    return records_root


def create_realized_gains_skeleton(parent_folder: Path, year: int, config_path: Path = LOCAL_CONFIG_PATH) -> Path:
    """Create the standard records layout beneath a user-selected parent folder."""
    records_root = create_realized_gains_layout(parent_folder, year)
    return save_realized_gains_root(records_root, config_path)


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


def carryover_loss_defaults(config_path: Path = LOCAL_CONFIG_PATH) -> tuple[str, str]:
    """Return persisted short- and long-term capital-loss carryovers."""
    config = _local_config(config_path)
    return (str(config.get("short_term_carryover_loss", "0")), str(config.get("long_term_carryover_loss", "0")))


def save_tax_input_defaults(values: dict[str, list[str]], config_path: Path = LOCAL_CONFIG_PATH) -> None:
    """Persist tax-profile inputs without exposing or replacing API credentials."""
    profile_keys = {"state", "other_ordinary_taxable_income", "short_term_carryover_loss", "long_term_carryover_loss", "filing_status", "num_dependents", "ai_provider"}
    if not profile_keys.intersection(values):
        return
    state = values.get("state", [""])[0].strip().upper()
    income = _non_negative_currency(values.get("other_ordinary_taxable_income", ["0"])[0])
    config = _local_config(config_path)
    config["state_residence"] = state
    config["other_ordinary_taxable_income"] = income
    config["short_term_carryover_loss"] = _non_negative_currency(values.get("short_term_carryover_loss", ["0"])[0])
    config["long_term_carryover_loss"] = _non_negative_currency(values.get("long_term_carryover_loss", ["0"])[0])
    if "filing_status" in values:
        config["filing_status"] = values["filing_status"][0].strip()
    if "num_dependents" in values:
        try:
            config["num_dependents"] = max(0, int(values["num_dependents"][0]))
        except (TypeError, ValueError):
            pass
    if "ai_provider" in values:
        config["ai_provider"] = values["ai_provider"][0].strip().lower()
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
