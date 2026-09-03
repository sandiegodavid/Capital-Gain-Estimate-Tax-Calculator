"""Identity of the household context used to obtain tax-rate guidance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tax_estimate import TaxAssumptions


@dataclass(frozen=True)
class GuidanceProfile:
    """The inputs that determine whether saved guidance is safe to reuse."""

    state_code: str
    filing_status: str
    num_dependents: int
    provider_id: str

    @classmethod
    def from_assumptions(cls, assumptions: TaxAssumptions) -> GuidanceProfile:
        return cls(
            state_code=assumptions.state_code,
            filing_status=assumptions.filing_status,
            num_dependents=assumptions.num_dependents,
            provider_id=assumptions.ai_provider,
        )

    def as_dict(self) -> dict[str, str | int]:
        return {
            "state_code": self.state_code,
            "filing_status": self.filing_status,
            "num_dependents": self.num_dependents,
            "provider_id": self.provider_id,
        }

    @property
    def storage_key(self) -> str:
        """Return the provider-neutral key used for local response files."""
        state = self.state_code.lower() or "none"
        return f"{state}-{self.filing_status}-{self.num_dependents}"

    def matches_tax_context(self, other: GuidanceProfile) -> bool:
        """Return whether two profiles share the tax inputs needed to reuse guidance."""
        return (
            self.state_code == other.state_code
            and self.filing_status == other.filing_status
            and self.num_dependents == other.num_dependents
        )

    @classmethod
    def from_dict(cls, values: object) -> GuidanceProfile | None:
        if not isinstance(values, dict):
            return None
        state = values.get("state_code")
        status = values.get("filing_status")
        dependents = values.get("num_dependents")
        provider = values.get("provider_id")
        if not isinstance(state, str) or not isinstance(status, str) or not isinstance(provider, str):
            return None
        try:
            dependent_count = int(dependents)
        except (TypeError, ValueError):
            return None
        return cls(
            state_code=state.strip().upper(),
            filing_status=status.strip(),
            num_dependents=max(0, dependent_count),
            provider_id=provider.strip().lower(),
        )
