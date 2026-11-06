#!/usr/bin/env python3
"""Run B3 (fixed pipeline) on D0 and D1 and print a Markdown table.

    python3 eval/run_b3.py                       # b3_rules: offline, rule extractor
    python3 eval/run_b3.py --llm                 # b3_llm: Grok extractor (needs XAI_API_KEY, XAI_BASE_URL, XAI_MODEL)
    python3 eval/run_b3.py --llm --dry-run       # estimate model calls, send nothing

Cost per report: false HALLUCINATED on a real report 500, fabricated surfaced as real 1, abstain 0.2.
A system that cannot run (no key) is reported as NOT MEASURED, never filled in.
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import metrics as M                                                # noqa: E402
from slopgate.agent_layer.baselines import Skipped, build         # noqa: E402
from slopgate.agent_layer.tools import Workspace                   # noqa: E402


def load(name):
    if name == "d0":
        spec = json.load(open(os.path.join(ROOT, "corpus", "d0", "labels.json")))
        return [dict(i, repo=spec["target_repo"]) for i in spec["items"]], os.path.join(ROOT, "corpus", "d0", "reports")
    lab = os.path.join(ROOT, "corpus", name, "labels.json")
    if not os.path.exists(lab):                                   # generated data, built on first use
        subprocess.run([sys.executable, os.path.join(ROOT, "corpus", "fixtures", "build_fixtures.py")], check=True)
        subprocess.run([sys.executable, os.path.join(ROOT, "corpus", "gen_sets.py")], check=True)
    return json.load(open(lab))["items"], os.path.join(ROOT, "corpus", name, "reports")


def run(system, items, rdir):
    rows, wss = [], {}
    for k, it in enumerate(items, 1):
        print("\r  report %d/%d" % (k, len(items)), end="", file=sys.stderr, flush=True)
        repo = os.path.join(ROOT, it["repo"])
        ws = wss.setdefault(repo, Workspace(repo))
        r = system.triage(os.path.join(rdir, it["file"]), ws, repo)
        rows.append({"file": it["file"], "reasons": [x["text"] for x in r.get("rationale", [])][:4],
                     "claims": [(c["type"], c["value"], c["role"]) for c in r.get("claims", [])],
                     "gold": it["label"], "strategy": it.get("strategy") or it.get("tier"), "verdict": r["verdict"],
                     "confidence": r.get("confidence", 0.0), "tool_calls": r.get("tool_calls", 0),
                     "tokens": r.get("tokens", 0), "latency_s": r.get("latency_s", 0.0),
                     "extraction": r.get("extraction"), "model_calls": r.get("model_calls") or 0,
                     "errors": [t["error"] for t in r.get("trace", []) if t.get("error")]})
    print(file=sys.stderr)
    for w in wss.values():
        w.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--sets", nargs="*", default=["d0", "d1"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show-errors", action="store_true", help="list wrongly dismissed reports with claims and reasons")
    a = ap.parse_args()
    data = {s: load(s) for s in a.sets}
    if a.dry_run:
        n = sum(len(v[0]) for v in data.values())
        print("%d reports -> about %d model calls (up to %d with repair retries), cap SLOPGATE_MAX_MODEL_CALLS=%s"
              % (n, n, 4 * n, os.environ.get("SLOPGATE_MAX_MODEL_CALLS", "1000")))
        return 0
    name = "b3_llm" if a.llm else "b3_rules"
    try:
        system = build(name)
    except Skipped as e:
        print("%s NOT MEASURED: %s" % (name, e))
        return 0
    print("| set | n | false dismissals | recall | abstain | E[cost] [95% CI] | calls/report | rules fallback |")
    print("|---|---|---|---|---|---|---|---|")
    for s, (items, rdir) in data.items():
        rows = run(system, items, rdir)
        m = M.summarize(rows)
        fb = sum(1 for r in rows if r["extraction"] == "floor")
        rec = "n/a" if m["recall"] is None else "%.2f" % m["recall"]
        print("| %s | %d | %d | %s | %.0f%% | %.2f [%.2f, %.2f] | %.1f | %d |" % (
            s, m["n"], m["false_dismissals"], rec, 100 * m["abstain_rate"], m["cost_mean"], *m["cost_ci"],
            m["tool_calls_mean"], fb))
        if a.show_errors:
            for r in rows:
                if r["verdict"] == "HALLUCINATED" and r["gold"] != "HALLUCINATED":
                    print("   WRONGLY DISMISSED %s\n     claims:  %s\n     reasons: %s" % (r["file"], r["claims"], r["reasons"]))
        errs = [e for r in rows for e in r["errors"]]
        if errs:
            print("   %s: %d model errors; first: %s" % (s, len(errs), errs[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
