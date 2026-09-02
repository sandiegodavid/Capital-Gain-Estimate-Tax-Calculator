"""Capital Gain Estimate Tax Calculator application package."""

from .models import NormalizedReport, ReportError
from .normalizer import normalize_sources
from .service import generate_report

__all__ = ["NormalizedReport", "ReportError", "generate_report", "normalize_sources"]
