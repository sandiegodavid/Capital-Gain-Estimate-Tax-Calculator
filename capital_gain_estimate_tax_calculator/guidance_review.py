"""Application service for reviewing and applying AI tax guidance responses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .guidance_mapping import (
    GuidanceResponse,
    TaxRateMapping,
    decode_guidance_response,
    map_bracket_rates,
    validate_guidance_response,
)
from .guidance_profile import GuidanceProfile
from .guidance_store import GuidanceResponseRepository, GuidanceResponseStore, SavedGuidanceResponse
from .tax_estimate import TaxAssumptions
from .tax_guidance import request_tax_rate_guidance


@dataclass(frozen=True)
class AppliedGuidance:
    """A validated response, its mapped rates, and its updated assumptions."""

    assumptions: TaxAssumptions
    response: GuidanceResponse
    mapping: TaxRateMapping
    path: Path


class GuidanceReviewService:
    """Coordinate provider results, validation, mapping, and local response storage."""

    def __init__(
        self,
        request_guidance: Callable[[int, TaxAssumptions], str] = request_tax_rate_guidance,
        response_store: GuidanceResponseRepository | None = None,
    ) -> None:
        self._request_guidance = request_guidance
        self._response_store = response_store or GuidanceResponseStore()

    def request_candidate(self, year: int, assumptions: TaxAssumptions) -> GuidanceResponse:
        """Request and validate one response candidate from the selected provider."""
        response = decode_guidance_response(self._request_guidance(year, assumptions))
        return validate_guidance_response(response, assumptions.filing_status)

    def load_candidates(self, output_dir: Path, year: int, assumptions: TaxAssumptions) -> tuple[GuidanceResponse, ...]:
        """Return every saved candidate compatible with the current household inputs."""
        saved = self.load_saved_candidates(output_dir, year, assumptions)
        return tuple(validate_guidance_response(item.response, assumptions.filing_status) for item in saved)

    def load_saved_candidates(
        self,
        output_dir: Path,
        year: int,
        assumptions: TaxAssumptions,
    ) -> tuple[SavedGuidanceResponse, ...]:
        """Return saved candidates with their local review metadata."""
        return self._response_store.load_all(output_dir, year, self._profile(assumptions))

    def load_selected(self, output_dir: Path, year: int, assumptions: TaxAssumptions) -> AppliedGuidance | None:
        """Load and apply the locally selected candidate, if one exists."""
        saved = self._response_store.load_selected(output_dir, year, self._profile(assumptions))
        if saved is None:
            return None
        return self.apply(saved.response, assumptions, saved.path)

    def save_candidates(
        self,
        output_dir: Path,
        year: int,
        assumptions: TaxAssumptions,
        responses: list[GuidanceResponse],
        selected_index: int,
        source_providers: list[str] | None = None,
        manually_updated: list[bool] | None = None,
    ) -> tuple[Path, ...]:
        """Validate and save each reviewed candidate with one selected marker."""
        validated = [validate_guidance_response(response, assumptions.filing_status) for response in responses]
        return self._response_store.save(
            output_dir,
            year,
            self._profile(assumptions),
            validated,
            selected_index,
            source_providers,
            manually_updated,
        )

    @staticmethod
    def _profile(assumptions: TaxAssumptions) -> GuidanceProfile:
        """Translate tax assumptions once at the persistence boundary."""
        return GuidanceProfile.from_assumptions(assumptions)

    def apply(self, response: GuidanceResponse, assumptions: TaxAssumptions, path: Path) -> AppliedGuidance:
        """Map one validated response to the rates applicable to this household."""
        validated = validate_guidance_response(response, assumptions.filing_status)
        mapping = map_bracket_rates(validated, assumptions.other_ordinary_taxable_income)
        return AppliedGuidance(assumptions, validated, mapping, path)
