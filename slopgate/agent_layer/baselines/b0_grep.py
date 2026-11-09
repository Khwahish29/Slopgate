"""B0: grep. The floor from Milestone 1: what a hurried maintainer does.

The report is called HALLUCINATED only if the primary claimed symbol occurs nowhere in the working
tree (any file, comments and docs included); otherwise UNVERIFIED. No model, no ref, no history."""
import os
import time

from .. import extract
from ..llm import validate_claims
from ..prose_extract import ProseRuleBackend
from .base import System, register

SKIP_DIRS = {".git"}


def grep_tree(root, needle):
    hits = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            p = os.path.join(d, f)
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if needle in line:
                            hits.append({"file": os.path.relpath(p, root), "line": i})
            except OSError:
                continue
    return hits


@register("b0")
class B0Grep(System):
    description = "B0 grep (primary symbol anywhere in the working tree)"

    def __init__(self, env=None):
        self.backend = ProseRuleBackend()

    def triage(self, report_path, ws, repo):
        t0 = time.time()
        clean, injection = extract.sanitize(open(report_path, encoding="utf-8").read())
        claims, _ = validate_claims(self.backend.extract(clean), clean)
        syms = [c for c in claims if c["type"] == "symbol"]
        syms.sort(key=lambda c: c["role"] != "load-bearing")
        sym = syms[0]["value"] if syms else None
        hits = grep_tree(ws.repo, sym) if sym else []
        verdict = "HALLUCINATED" if sym and not hits else "UNVERIFIED"
        why = ("'%s' not found anywhere in the tree" % sym) if verdict == "HALLUCINATED" else \
              ("'%s' found (%d hits)" % (sym, len(hits)) if sym else "no symbol claim extracted")
        return {"report": os.path.basename(report_path), "verdict": verdict,
                "confidence": 0.6 if verdict == "HALLUCINATED" else 0.3, "tool_calls": 1,
                "tokens": 0, "model_calls": 0, "latency_s": time.time() - t0,
                "injection_flags": injection, "claims": claims, "method": self.description,
                "rationale": [{"text": why, "cites": []}], "ledger": [], "trace": []}
