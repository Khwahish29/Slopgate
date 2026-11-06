"""SlopGate package."""

from .models import Claim, EvidenceRow, VerdictResult
from .core import analyze_report
from .claim_extractor import extract_claims_balanced

__all__ = [
    "Claim",
    "EvidenceRow",
    "VerdictResult",
    "analyze_report",
    "extract_claims_balanced",
]
