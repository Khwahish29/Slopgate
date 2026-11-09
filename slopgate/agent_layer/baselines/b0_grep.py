
"""B0: naive repository-wide symbol grep baseline.

B0 checks whether the primary symbol claimed in a report
appears anywhere in the repository.

This is intentionally a weak baseline:
- No LLM calls
- No semantic verification
- No reachability checks
- No version validation
- No path or line validation

A symbol match is treated as evidence against hallucination,
not proof that a vulnerability is reproducible.
"""

import os
import time
from pathlib import Path

from .. import extract
from ..llm import validate_claims
from ..prose_extract import ProseRuleBackend
from .base import System, register


SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}

MAX_FILE_SIZE = 2 * 1024 * 1024


def extract_primary_symbol(report_text):
    """Extract the primary claimed symbol using existing rules."""
    backend = ProseRuleBackend()

    clean, _ = extract.sanitize(report_text)
    claims, _ = validate_claims(
        backend.extract(clean),
        clean,
    )

    symbols = [
        claim
        for claim in claims
        if claim.get("type") == "symbol"
    ]

    if not symbols:
        return None

    symbols.sort(
        key=lambda claim: (
            claim.get("role") != "load-bearing"
        )
    )

    return symbols[0]["value"]


def grep_repository(repo, symbol):
    """Return whether a symbol appears in repository files."""
    root = Path(repo)

    if not root.is_dir():
        raise FileNotFoundError(repo)

    files_checked = 0

    for current_root, directories, filenames in os.walk(root):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in SKIP_DIRS
        )

        for filename in sorted(filenames):
            path = Path(current_root) / filename

            try:
                if not path.is_file():
                    continue

                if path.stat().st_size > MAX_FILE_SIZE:
                    continue

                with path.open(
                    "r",
                    encoding="utf-8",
                    errors="ignore",
                ) as file:
                    content = file.read()

                files_checked += 1

                if symbol in content:
                    return True, files_checked

            except (OSError, UnicodeError):
                continue

    return False, files_checked


@register("b0")
class B0Grep(System):
    description = (
        "B0 naive grep baseline: primary symbol existence "
        "anywhere in repository"
    )

    def __init__(self):
        self.backend = ProseRuleBackend()

    def triage(self, report_path, ws, repo):
        started = time.perf_counter()

        report_text = Path(report_path).read_text(
            encoding="utf-8"
        )

        symbol = extract_primary_symbol(report_text)

        if symbol is None:
            verdict = "UNVERIFIED"
            confidence = 0.0
            matched = None
            files_checked = 0
            reason = "No claimed symbol could be extracted."

        else:
            matched, files_checked = grep_repository(
                repo,
                symbol,
            )

            if matched:
                verdict = "UNVERIFIED"
                confidence = 0.5
                reason = (
                    f"Claimed symbol {symbol!r} appears "
                    "somewhere in the repository."
                )
            else:
                verdict = "HALLUCINATED"
                confidence = 0.5
                reason = (
                    f"Claimed symbol {symbol!r} was not found "
                    "in the scanned repository files."
                )

        return {
            "report": Path(report_path).name,
            "verdict": verdict,
            "confidence": confidence,
            "tool_calls": 0,
            "tokens": 0,
            "model_calls": 0,
            "latency_s": time.perf_counter() - started,
            "method": self.description,
            "symbol": symbol,
            "symbol_found": matched,
            "files_checked": files_checked,
            "rationale": [
                {
                    "text": reason,
                    "cites": [],
                }
            ],
            "ledger": [],
            "trace": [
                {
                    "step": "grep",
                    "symbol": symbol,
                    "found": matched,
                    "files_checked": files_checked,
                }
            ],
        }
