from __future__ import annotations

import re
from typing import List

from .models import Claim


def extract_claims_balanced(report_text: str) -> List[Claim]:
    """Extract structured claims from prose-style vulnerability reports."""
    claims: List[Claim] = []
    text = report_text.strip()
    if not text:
        return [Claim(id="C1", type="statement", value="", span="", role="supporting", source="empty")]

    candidates = []
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if any(token in lowered for token in ["function", "symbol", "file", "path", "line", "vulnerab", "issue", "cve", "commit"]):
            candidates.append(cleaned)

    if not candidates:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        candidates = [s for s in sentences if len(s) > 10]

    for idx, candidate in enumerate(candidates[:10], start=1):
        lowered = candidate.lower()
        role = "load-bearing" if any(token in lowered for token in ["vulnerab", "issue", "exploit", "overflow", "memory", "null", "panic"]) else "supporting"
        claims.append(
            Claim(
                id=f"C{idx}",
                type="reference" if any(token in lowered for token in ["function", "file", "path", "line", "symbol"]) else "statement",
                value=candidate,
                span=candidate,
                role=role,
                source="balanced-extractor",
            )
        )

    return claims
