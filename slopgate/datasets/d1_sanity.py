"""Dataset sanity check: run key-free systems over D1 under each grounding parser.

    python -m slopgate.datasets.d1_sanity                       # b1 and b3_rules, both parsers
    python -m slopgate.datasets.d1_sanity --systems b1 --parsers treesitter

This is the dataset author's consistency check, not the evaluation: the harness (Step 5) is
where reported numbers come from. "correct" means the system returned the item's
expected_verdict (HALLUCINATED for hallucinated reports, UNVERIFIED for real ones).
A false HALLUCINATED is a real report the system would auto-close: the costly error.
"""
import argparse
import collections
import json
import os
import sys

from ..agent_layer import ground, ts_ground
from ..agent_layer.baselines import build
from ..agent_layer.tools import Workspace
from .d1 import load

TIERS = ("T1", "T2", "T3", "T4", "T5")


def run(items, system, parser):
    os.environ["SLOPGATE_PARSER"] = parser
    s, ws, rows = build(system), {}, []
    for it in items:
        w = ws.setdefault(it["repo"], Workspace(it["repo"]))
        v = s.triage(it["report_path"], w, it["repo"])["verdict"]
        rows.append({"id": it["id"], "tier": it["tier"], "repo": it["id"].split("-")[1], "gold": it["gold"],
                     "expected": it["expected_verdict"], "got": v})
    for w in ws.values():
        w.close()
    return rows


def summarize(rows):
    ok = collections.Counter((r["tier"], r["got"] == r["expected"]) for r in rows)
    false_h = [r for r in rows if r["gold"] == "NOT_HALLUCINATED" and r["got"] == "HALLUCINATED"]
    missed = [r for r in rows if r["gold"] == "HALLUCINATED" and r["got"] != "HALLUCINATED"]
    return {"correct": sum(1 for r in rows if r["got"] == r["expected"]), "n": len(rows),
            "by_tier": {t: "%d/%d" % (ok[(t, True)], ok[(t, True)] + ok[(t, False)]) for t in TIERS},
            "false_hallucinated": len(false_h), "missed_hallucinated": len(missed),
            "false_hallucinated_by_repo": dict(collections.Counter(r["repo"] for r in false_h))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", default=os.path.join("corpus", "d1", "d1.jsonl"))
    ap.add_argument("--systems", nargs="+", default=["b1", "b3_rules"])
    ap.add_argument("--parsers", nargs="+", default=["regex", "treesitter"], choices=["regex", "treesitter"])
    ap.add_argument("--json", action="store_true", help="print one JSON object instead of a table")
    a = ap.parse_args(argv)
    if "treesitter" in a.parsers and not ts_ground.available():
        print("tree-sitter not installed (%s); running regex only" % ts_ground.IMPORT_ERROR, file=sys.stderr)
        a.parsers = [p for p in a.parsers if p != "treesitter"]
    items = load(a.data)
    saved = os.environ.get("SLOPGATE_PARSER")
    out = {}
    try:
        for p in a.parsers:
            for s in a.systems:
                out["%s/%s" % (s, p)] = summarize(run(items, s, p))
                assert ground.parser_mode() == p
    finally:
        if saved is None:
            os.environ.pop("SLOPGATE_PARSER", None)
        else:
            os.environ["SLOPGATE_PARSER"] = saved
    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    print("%-22s %9s  %s  %8s  %6s" % ("system/parser", "correct", "  ".join("%-7s" % t for t in TIERS), "false-H", "missed"))
    for k, r in out.items():
        print("%-22s %4d/%-4d  %s  %8d  %6d" % (k, r["correct"], r["n"], "  ".join("%-7s" % r["by_tier"][t] for t in TIERS),
                                               r["false_hallucinated"], r["missed_hallucinated"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
