"""B3: fixed pipeline. Extract, then EVERY tool on EVERY claim in a fixed order, then the
rule adjudicator decides. No planning, no stopping rule, no skeptic, no proposer.

Isolates the value of planning and stopping, apart from reading. b3_rules extracts with
the offline prose extractor; b3_llm extracts with Grok (needs a key)."""
import os
import time

from .. import extract, verifier
from ..ledger import Ledger
from ..llm import LLMBackend, ModelError, OpenAICompatClient, ProseRuleBackend, RuleBackend, validate_claims
from ..tools import run_tool
from .base import Skipped, System, register


FLOOR = RuleBackend()
GOOD = {"DEFINED", "EXISTS", "LOCATED", "IN_RANGE", "FOUND", "REACHABLE"}


def extract_claims(clean, backend, trace):
    """Model extraction with the verbatim-span rule; two schema failures -> regex floor."""
    discarded, failures = [], 0
    if backend.name != "rules":
        while failures < 2:
            try:
                raw = backend.extract(clean)
                claims, bad = validate_claims(raw, clean)
                discarded += bad
                if not claims:
                    first = bad[0] if bad else {}
                    trace.append({"step": "extract", "error": "model returned %d claims, none usable; first: %s | %s" % (
                        len(raw), first.get("why", "empty list"), str(first.get("claim", ""))[:160])})
                if claims:
                    trace.append({"step": "extract", "source": backend.name,
                                  "claims": len(claims), "discarded": len(bad)})
                    return claims, discarded
                failures += 1                       # nothing survived the span rule
            except (ValueError, KeyError, TypeError, ModelError) as e:
                failures += 1
                trace.append({"step": "extract", "error": str(e)[:120]})
    claims, _ = validate_claims(FLOOR.extract(clean), clean)
    trace.append({"step": "extract", "source": "rules (floor)", "claims": len(claims)})
    return claims, discarded


def rank_inputs(L):
    rel = [r for r in L.rows if r["tool"] in ("find_symbol", "check_path", "symbol_in_file",
                                              "check_line_range") and r["status"] != "INCONCLUSIVE"]
    return sum(1 for r in rel if r["status"] in GOOD) / len(rel) if rel else 0.0


def fixed_order(claims):
    """Deterministic call list, a function of the claim set only (never of earlier results).

    Every tool runs on every claim it applies to:
      tag     -> resolve_tag
      symbol  -> find_symbol, git_history, check_reachability
      path    -> check_path
      symbol x path -> symbol_in_file (every pair)
      line x path   -> check_line_range (every pair)
    """
    syms = [c["value"] for c in claims if c["type"] == "symbol"]
    paths = [c["value"] for c in claims if c["type"] == "path"]
    lines = [c["value"] for c in claims if c["type"] == "line"]
    calls = [("resolve_tag", {"version": c["value"]}) for c in claims if c["type"] == "tag"]
    calls += [("find_symbol", {"name": s}) for s in syms]
    calls += [("check_path", {"path": p}) for p in paths]
    calls += [("symbol_in_file", {"name": s, "path": p}) for s in syms for p in paths]
    calls += [("check_line_range", {"path": p, "line": n}) for n in lines for p in paths]
    for s in syms:
        calls.append(("git_history", {"name": s}))
        calls.append(("check_reachability", {"name": s}))
    return calls


REF_AWARE = ("find_symbol", "check_path", "symbol_in_file", "check_line_range", "check_reachability")


class _B3(System):
    backend = None

    def triage(self, report_path, ws, repo):
        t0 = time.time()
        raw = open(report_path, encoding="utf-8").read()
        clean, injection = extract.sanitize(raw)
        client = getattr(self.backend, "client", None)
        tok0, calls0 = getattr(client, "tokens", 0), getattr(client, "calls", 0)
        trace = []
        claims, discarded = extract_claims(clean, self.backend, trace)
        source = next((t.get("source") for t in reversed(trace) if t.get("step") == "extract" and "source" in t), "?")
        L = Ledger()
        ref = None                                   # first tag that resolves; later calls use it
        for tool, args in fixed_order(claims):
            if ref and tool in REF_AWARE:
                args = dict(args, ref=ref)
            row = L.add(tool, args, run_tool(ws, tool, args), by="fixed")
            if tool == "resolve_tag" and ref is None and row["result"].get("tag"):
                ref = row["result"]["tag"]
        det = verifier.deterministic_verdict(L, claims, injection)
        return {"report": os.path.basename(report_path), "verdict": det["verdict"],
                "confidence": det["confidence"], "tool_calls": len(L.rows),
                "tokens": getattr(client, "tokens", 0) - tok0,
                "model_calls": getattr(client, "calls", 0) - calls0,
                "extraction": "floor" if "floor" in str(source) else source,
                "discarded_claims": len(discarded), "claims": claims,
                "latency_s": time.time() - t0, "injection_flags": injection,
                "grounded_fraction": rank_inputs(L), "method": self.description,
                "rationale": [{"text": x, "cites": []} for x in det["reasons"]], "ledger": L.dump(),
                "trace": trace}


@register("b3_rules")
class FixedRules(_B3):
    description = "B3 fixed pipeline (offline prose extractor, all tools, rule adjudicator)"

    def __init__(self, env=None):
        self.backend = ProseRuleBackend()


@register("b3_llm", needs_llm=True)
class FixedLLM(_B3):
    description = "B3 fixed pipeline (Grok extractor, all tools, rule adjudicator)"

    def __init__(self, env=None):
        try:
            client = OpenAICompatClient.from_env("XAI", "https://api.x.ai/v1", ".slopgate_cache")
            client.max_calls = int(os.environ.get("SLOPGATE_MAX_MODEL_CALLS", "1000"))
            self.backend = LLMBackend(client, "grok")
        except Exception as e:  # noqa: BLE001
            raise Skipped(str(e))
