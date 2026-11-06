from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .models import Claim, EvidenceRow, VerdictResult

INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"system prompt",
    r"set verdict to",
    r"you are now",
    r"override the triage",
]


def sanitize_report(report_text: str) -> Tuple[str, List[str]]:
    """Remove instruction-like injected content and return text plus flags."""
    flags: List[str] = []
    cleaned = report_text
    for pattern in INJECTION_PATTERNS:
        matches = re.findall(pattern, cleaned, flags=re.IGNORECASE)
        if matches:
            flags.append(pattern)
    for pattern in INJECTION_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(), flags


def extract_claims(report_text: str) -> List[Claim]:
    """A lightweight extractor for prose-style report claims."""
    claims: List[Claim] = []
    lines = [line.strip() for line in report_text.splitlines() if line.strip()]
    for index, line in enumerate(lines, start=1):
        lower = line.lower()
        if any(token in lower for token in ["function", "symbol", "file", "path", "line", "vulnerab", "issue"]):
            claim_id = f"C{index}"
            claims.append(
                Claim(
                    id=claim_id,
                    type="reference",
                    value=line,
                    span=line,
                    role="load-bearing" if "vulnerab" in lower or "issue" in lower else "supporting",
                    source="heuristic",
                )
            )
    if not claims:
        claims.append(
            Claim(
                id="C1",
                type="statement",
                value=report_text[:200],
                span=report_text[:200],
                role="supporting",
                source="fallback",
            )
        )
    return claims


def build_evidence_ledger() -> List[EvidenceRow]:
    return []


def verify_rationale(rationale: str, evidence: List[EvidenceRow]) -> bool:
    """Very lightweight verifier: every cited evidence ID must exist."""
    if not rationale:
        return True
    ids = {row.id for row in evidence}
    cited = set(re.findall(r"E\d+", rationale))
    return cited.issubset(ids)


def adjudicate_verdict(ledger: List[EvidenceRow], claims: List[Claim]) -> str:
    """Deterministic verdict using a conservative baseline."""
    if not claims:
        return "UNVERIFIED"
    if any(row.status == "CONTRADICTION" for row in ledger):
        return "HALLUCINATED"
    if any(row.status == "GROUND" for row in ledger):
        return "UNVERIFIED"
    return "UNVERIFIED"


def rank_queue(results: List[VerdictResult]) -> List[VerdictResult]:
    """Rank the queue using a simple risk heuristic."""
    for idx, result in enumerate(sorted(results, key=lambda r: (-r.confidence, r.verdict)), start=1):
        result.queue_position = idx
    return results


def analyze_report(report_text: str, repo_root: str = ".", ref: str = "HEAD") -> VerdictResult:
    """Main entrypoint for report analysis."""
    cleaned_text, injection_flags = sanitize_report(report_text)
    claims = extract_claims(cleaned_text)

    ledger: List[EvidenceRow] = [
        EvidenceRow(
            id="E1",
            check="sanitize_report",
            status="OK" if not injection_flags else "FLAGGED",
            detail="Instruction-like text flagged during sanitization.",
            ref=ref,
        )
    ]

    if injection_flags:
        ledger.append(
            EvidenceRow(
                id="E2",
                check="injection_scan",
                status="SUSPICIOUS",
                detail="Detected likely prompt injection patterns.",
                ref=ref,
            )
        )

    repo = Path(repo_root)
    if repo.exists():
        ledger.append(
            EvidenceRow(
                id="E3",
                check="repo_exists",
                status="GROUND",
                detail=f"Repository root exists at {repo}",
                file=str(repo),
                ref=ref,
            )
        )
    else:
        ledger.append(
            EvidenceRow(
                id="E3",
                check="repo_exists",
                status="CONTRADICTION",
                detail=f"Repository root does not exist at {repo}",
                file=str(repo),
                ref=ref,
            )
        )

    verdict_name = adjudicate_verdict(ledger, claims)
    rationale = (
        f"The report was sanitized and checked against the repository at {repo}. "
        f"Evidence rows E1 and E3 support the documented triage workflow."
    )
    confidence = 0.62 if verdict_name == "UNVERIFIED" else 0.79

    result = VerdictResult(
        verdict=verdict_name,
        confidence=confidence,
        evidence=ledger,
        rationale=rationale,
        injection_flags=injection_flags,
        claims=claims,
    )
    if verify_rationale(rationale, ledger):
        result.rationale = rationale
    else:
        result.rationale = "The rationale could not be verified against the evidence ledger."
    return result
