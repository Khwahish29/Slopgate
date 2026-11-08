"""B1: deterministic single-pass baseline. No model anywhere.

  sanitize -> prose claim extractor -> ground the PRIMARY claims once -> rule adjudicator

Compared with B3 (b3_rules / b3_llm), B1 does not run every tool on every claim:
it checks only what the adjudicator keys on (the load-bearing symbol, path, line
and the version tag), plus existence of secondary symbols. No git history, no
second pass. It answers "what does careful reading plus one round of grounding
buy, with zero model cost?", the number every LLM stage has to beat.
"""
import os
import time

from .. import extract, verifier
from ..ledger import Ledger
from ..llm import validate_claims
from ..prose_extract import ProseRuleBackend
from ..tools import run_tool
from .base import System, register
from .b3_fixed import REF_AWARE, rank_inputs


def primary_plan(claims):
    """Tool calls for the primary claims only. Order: tag first, so a resolved
    ref is used by every later call."""
    def lb(t):
        c = [x for x in claims if x["type"] == t]
        c.sort(key=lambda x: x["role"] != "load-bearing")
        return c[0]["value"] if c else None

    sym, path, line, tag = lb("symbol"), lb("path"), lb("line"), lb("tag")
    calls = []
    if tag:
        calls.append(("resolve_tag", {"version": tag}))
    if sym:
        calls.append(("find_symbol", {"name": sym}))
    for c in claims:                                    # secondary symbols: existence only
        if c["type"] == "symbol" and c["value"] != sym:
            calls.append(("find_symbol", {"name": c["value"]}))
    if path:
        calls.append(("check_path", {"path": path}))
    if sym and path:
        calls.append(("symbol_in_file", {"name": sym, "path": path}))
    if path and line is not None:
        calls.append(("check_line_range", {"path": path, "line": int(line)}))
    if sym:
        calls.append(("check_reachability", {"name": sym}))
    return calls


@register("b1")
class B1Rules(System):
    description = "B1 single-pass rules (prose extractor, primary-claim grounding, rule adjudicator)"

    def __init__(self, env=None):
        self.backend = ProseRuleBackend()

    def triage(self, report_path, ws, repo):
        t0 = time.time()
        raw = open(report_path, encoding="utf-8").read()
        clean, injection = extract.sanitize(raw)
        claims, discarded = validate_claims(self.backend.extract(clean), clean)
        L = Ledger()
        ref = None
        for tool, args in primary_plan(claims):
            if ref and tool in REF_AWARE:
                args = dict(args, ref=ref)
            row = L.add(tool, args, run_tool(ws, tool, args), by="b1")
            if tool == "resolve_tag" and row["result"].get("tag"):
                ref = row["result"]["tag"]
        det = verifier.deterministic_verdict(L, claims, injection)
        return {"report": os.path.basename(report_path), "verdict": det["verdict"],
                "confidence": det["confidence"], "tool_calls": len(L.rows),
                "tokens": 0, "model_calls": 0, "extraction": self.backend.name,
                "discarded_claims": len(discarded), "claims": claims,
                "latency_s": time.time() - t0, "injection_flags": injection,
                "grounded_fraction": rank_inputs(L), "method": self.description,
                "rationale": [{"text": x, "cites": []} for x in det["reasons"]],
                "ledger": L.dump(), "trace": [{"step": "extract", "source": self.backend.name,
                                               "claims": len(claims), "discarded": len(discarded)}]}
