from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Claim:
    id: str
    type: str
    value: str
    span: str
    role: str = "supporting"
    source: str = "extracted"


@dataclass
class EvidenceRow:
    id: str
    check: str
    status: str
    detail: str
    file: Optional[str] = None
    line: Optional[int] = None
    ref: Optional[str] = None


@dataclass
class VerdictResult:
    verdict: str
    confidence: float
    evidence: List[EvidenceRow] = field(default_factory=list)
    rationale: str = ""
    queue_position: int = 0
    injection_flags: List[str] = field(default_factory=list)
    claims: List[Claim] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence": self.confidence,
            "evidence": [
                {
                    "id": row.id,
                    "check": row.check,
                    "status": row.status,
                    "detail": row.detail,
                    "file": row.file,
                    "line": row.line,
                    "ref": row.ref,
                }
                for row in self.evidence
            ],
            "rationale": self.rationale,
            "queue_position": self.queue_position,
            "injection_flags": self.injection_flags,
            "claims": [
                {
                    "id": claim.id,
                    "type": claim.type,
                    "value": claim.value,
                    "span": claim.span,
                    "role": claim.role,
                    "source": claim.source,
                }
                for claim in self.claims
            ],
        }
