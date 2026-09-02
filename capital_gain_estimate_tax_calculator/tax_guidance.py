"""Application service for planning-only AI tax-rate guidance."""

from __future__ import annotations

from collections.abc import Iterable

from .guidance_prompt import TaxGuidancePromptBuilder
from .guidance_providers import TaxGuidanceProvider, default_providers
from .models import ReportError
from .tax_estimate import TaxAssumptions, state_name


class TaxGuidanceService:
    """Coordinate state validation, prompt construction, and provider selection."""

    def __init__(
        self,
        providers: Iterable[TaxGuidanceProvider] | None = None,
        prompt_builder: TaxGuidancePromptBuilder | None = None,
    ) -> None:
        registered_providers = providers if providers is not None else default_providers()
        self._providers = {provider.provider_id: provider for provider in registered_providers}
        self._prompt_builder = prompt_builder or TaxGuidancePromptBuilder()

    def request(self, year: int, assumptions: TaxAssumptions) -> str:
        """Request guidance from the selected provider for a valid residence state."""
        residence = state_name(assumptions.state_code)
        if residence is None:
            raise ReportError("Select your state of residence before requesting AI rate guidance.")

        provider = self._providers.get(assumptions.ai_provider.lower())
        if provider is None:
            raise ReportError("Choose a supported AI provider for rate guidance.")
        return provider.request(self._prompt_builder.build(year, residence, assumptions))


_DEFAULT_SERVICE = TaxGuidanceService()


def request_tax_rate_guidance(year: int, assumptions: TaxAssumptions) -> str:
    """Request planning-only research through the configured AI provider."""
    return _DEFAULT_SERVICE.request(year, assumptions)
