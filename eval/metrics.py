"""Metrics for Milestone 1, Section 6.3. Pure functions; no I/O.

Cost matrix is the baseline's (adjudicate.COST): false HALLUCINATED on a real report 500,
a fabricated report surfaced as real 1, any abstention 0.2. Operational charges are placeholders
(the milestone says "small") and are reported separately so they cannot hide a decision error.
"""
import math
import random

from slopgate.agent_layer.adjudicate import COST

POS = "HALLUCINATED"
TOOL_CALL_USD = 0.0005          # placeholder; set from real prices before the final report
USD_PER_KTOK = 0.01             # placeholder


def decision_cost(gold, verdict):
    real = gold != POS
    if verdict == POS:
        return COST["false_hallucinated"] if real else 0.0
    if verdict == "UNVERIFIED":
        return COST["abstain"]
    return 0.0 if real else COST["false_reproducible"]


def bootstrap_ci(values, stat=None, n=2000, seed=7, alpha=0.05):
    """Percentile bootstrap of `stat` (default mean). Deterministic."""
    if not values:
        return (float("nan"), float("nan"))
    stat = stat or (lambda v: sum(v) / len(v))
    rng = random.Random(seed)
    k = len(values)
    est = sorted(stat([values[rng.randrange(k)] for _ in range(k)]) for _ in range(n))
    return est[int(alpha / 2 * n)], est[int((1 - alpha / 2) * n) - 1]


def pctl(values, q):
    if not values:
        return float("nan")
    v = sorted(values)
    return v[min(len(v) - 1, math.ceil(q * len(v)) - 1)]


def summarize(rows):
    """rows: dicts with gold, verdict, confidence, tool_calls, tokens, latency_s, tool_ok(optional)."""
    n = len(rows)
    tp = sum(1 for r in rows if r["verdict"] == POS and r["gold"] == POS)
    fp = sum(1 for r in rows if r["verdict"] == POS and r["gold"] != POS)
    fn = sum(1 for r in rows if r["verdict"] != POS and r["gold"] == POS)
    abst = sum(1 for r in rows if r["verdict"] == "UNVERIFIED")
    costs = [decision_cost(r["gold"], r["verdict"]) for r in rows]
    fabs = [r for r in rows if r["gold"] == POS]
    recall_vals = [1.0 if r["verdict"] == POS else 0.0 for r in fabs]
    ops = [r["tool_calls"] * TOOL_CALL_USD + r["tokens"] / 1000.0 * USD_PER_KTOK for r in rows]
    oks = [r["tool_ok"] for r in rows if r.get("tool_ok") is not None]
    return {
        "n": n, "tp": tp, "fp": fp, "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "recall_ci": bootstrap_ci(recall_vals) if recall_vals else None,
        "false_dismissals": fp,
        "abstain_rate": abst / n if n else None,
        "cost_mean": sum(costs) / n if n else None, "cost_ci": bootstrap_ci(costs),
        "ops_usd_mean": sum(ops) / n if n else None,
        "tool_calls_mean": sum(r["tool_calls"] for r in rows) / n if n else None,
        "tool_success": sum(oks) / len(oks) if oks else None,
        "latency_p50": pctl([r["latency_s"] for r in rows], 0.5),
        "latency_p95": pctl([r["latency_s"] for r in rows], 0.95),
        "tokens_mean": sum(r["tokens"] for r in rows) / n if n else None,
    }


