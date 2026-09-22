"""Small, framework-free HTML formatting helpers shared by views."""

from __future__ import annotations

import html
from decimal import Decimal


def currency(value: Decimal) -> str:
    prefix = "−" if value < 0 else ""
    return f"{prefix}${abs(value):,.2f}"


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def rule_label(value: object) -> str:
    return str(value).replace("_", " ").strip().capitalize()


def rule_value(value: object) -> str:
    if value is None:
        return "Not specified"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, dict):
        return "; ".join(f"{rule_label(key)}: {rule_value(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(rule_value(item) for item in value)
    return str(value)
