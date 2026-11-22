"""Demo driver: run one system on one report and show every step that led to the verdict.

    python -m slopgate.demo                                   # showcase: one D0 report per tier, B1
    python -m slopgate.demo --report r.md --repo path/to/repo --system b3_rules
    python -m slopgate.demo --data corpus/d3/d3.jsonl --id d3-pktbuf-t3-03-wrong_version --skeptic
    python -m slopgate.demo --showcase --system agent --json out.json     # needs XAI_* for the agent

Prints, in order: sanitizer signals, extracted claims (load-bearing first), the evidence ledger,
the verdict with its confidence and rationale, and optionally
  --skeptic   the skeptic pass on that ledger (rules; plus a model if SKEPTIC_* is set). For the
              agent the skeptic already ran inside finalize(); its objections are shown from the trace.
  --repro     the reproduction claims the sandbox would receive.
Nothing here changes a verdict that a system returned; the skeptic section is shown alongside it.
"""
import argparse
import json
import os
import sys

from .agent_layer import extract as ex
from .agent_layer.baselines import build
from .agent_layer.baselines.base import Skipped
from .agent_layer.ledger import Ledger
from .agent_layer.repro_extract import extract_repro
from .agent_layer.tools import Workspace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D0 = os.path.join(ROOT, "corpus", "d0")
SHOWCASE = [  # (file, why it is interesting)
    ("t1_a.md", "T1: the function is invented"),
    ("t2_a.md", "T2: the name only appears in a comment, never defined (grep says 'present')"),
    ("t3_a.md", "T3: real but hard to ground (abstain, do not close)"),
    ("t4_c.md", "T4: real, reachable function (needs a human: existence is not exploitability)"),
    ("t5_a.md", "T5: real function, real file, in-range line, but the function is not in that file"),
]


def _w(out, s=""):
    out.write(s + "\n")


def _short(v, n=70):
    s = json.dumps(v, default=str) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n - 3] + "..."


def run_one(system, report_path, repo, ws=None):
    own = ws is None
    ws = ws or Workspace(repo)
    try:
        return system.triage(report_path, ws, repo), ws
    finally:
        if own:
            ws.close()


def skeptic_view(res, report_path, ws):
    """Skeptic objections: from the agent's trace, or a fresh rules-only pass on a baseline's ledger."""
    final = next((s for s in reversed(res.get("trace") or []) if s.get("step") == "final"), None)
    if final is not None and "skeptic" in final:
        info = final.get("skeptic")
        return {"source": "agent finalize()", "ran": info is not None,
                "objections": (info or {}).get("objections", []),
                "events": [e for e in final.get("finalize_events", []) if "skeptic" in e]}
    if res["verdict"] != "HALLUCINATED":
        return {"source": "skeptic pass", "ran": False, "objections": [],
                "events": ["verdict is %s: the skeptic only challenges HALLUCINATED" % res["verdict"]]}
    from .agent_layer.skeptic import skeptic
    L = Ledger()
    L.rows = [dict(r) for r in res.get("ledger") or []]
    out = skeptic(open(report_path, encoding="utf-8").read(), L, res.get("claims") or [], ws, None)
    return {"source": "skeptic pass on this system's ledger", "ran": True, "objections": out["objections"],
            "verdict_after": out["verdict"], "new_rows": [r for r in L.rows if r["id"] in out["rows"]],
            "events": []}


def show(out, res, report_path, title=None, skeptic=None, repro=None):
    raw = open(report_path, encoding="utf-8").read()
    clean, signals = ex.sanitize(raw)
    head = next((ln.lstrip("# ").strip() for ln in raw.splitlines() if ln.strip()), "")
    _w(out, "=" * 78)
    _w(out, title or os.path.basename(report_path))
    _w(out, "report: %s" % head)
    _w(out, "system: %s" % res.get("method", "?"))
    _w(out, "-" * 78)
    _w(out, "sanitizer: %s" % ("clean" if not signals else "%d signal(s)" % len(signals)))
    for s in signals:
        _w(out, "  [%s] %s" % (s.get("kind", "known"), _short(s["span"], 70)))
    _w(out, "claims (extraction: %s):" % res.get("extraction", "?"))
    for c in sorted(res.get("claims") or [], key=lambda c: c.get("role") != "load-bearing"):
        _w(out, "  %-4s %-6s %-28s %s" % (c.get("id", ""), c["type"], _short(c["value"], 28),
                                          "LOAD-BEARING" if c.get("role") == "load-bearing" else "supporting"))
    _w(out, "evidence ledger:")
    for r in res.get("ledger") or []:
        _w(out, "  %-4s %-19s %-40s %s" % (r["id"], r["tool"], _short(r["args"], 40), r["status"]))
    _w(out, "-" * 78)
    _w(out, "VERDICT: %s   confidence %s   (%d tool calls, %s model calls)"
       % (res["verdict"], res.get("confidence"), res.get("tool_calls", 0), res.get("model_calls", 0)))
    for s in res.get("rationale") or []:
        _w(out, "  - %s" % _short(s.get("text", ""), 150))
    if skeptic is not None:
        _w(out, "skeptic (%s):" % skeptic["source"])
        for e in skeptic.get("events", []):
            _w(out, "  %s" % e)
        for r in skeptic.get("new_rows", []):
            _w(out, "  %-4s %-19s %-40s %s" % (r["id"], r["tool"], _short(r["args"], 40), r["status"]))
        for o in skeptic.get("objections", []):
            _w(out, "  objection [%s] %s  cites %s" % (o.get("rule"), _short(o.get("text", ""), 110), o.get("cites")))
        if skeptic.get("ran") and "verdict_after" in skeptic:
            _w(out, "  -> skeptic verdict: %s" % skeptic["verdict_after"])
        elif skeptic.get("ran") and not skeptic.get("objections"):
            _w(out, "  no objection: HALLUCINATED upheld")
    if repro is not None:
        _w(out, "repro claims (sandbox_ready=%s):" % repro["sandbox_ready"])
        for s in repro["steps"][:4]:
            _w(out, "  step: %s" % _short(s["text"], 100))
        for c in repro["commands"][:4]:
            _w(out, "  cmd:  %s%s" % (_short(c["cmd"], 90), "  RISKY %s" % c["risky"] if c["risky"] else ""))
        e = repro["expected"]
        if any(e.get(k) for k in ("sanitizer", "error", "signal", "crash_in")):
            _w(out, "  expected: %s %s %s crash_in=%s" % (e["sanitizer"] or "", e["error"] or "", e["signal"] or "",
                                                       e["crash_in"]))
        for n in repro["consistency"]["notes"]:
            _w(out, "  note: %s" % n)
    _w(out)


def cases_from_args(a):
    """[(report_path, repo, title)]"""
    if a.report:
        if not a.repo:
            raise SystemExit("--report needs --repo")
        return [(a.report, a.repo, None)]
    if a.data:
        from .datasets.d1 import load
        items = [it for it in load(a.data) if not a.id or it["id"] in a.id]
        if not items:
            raise SystemExit("no item with id %s in %s" % (a.id, a.data))
        return [(it["report_path"], it["repo"], "%s  (gold %s, tier %s)" % (it["id"], it["gold"], it.get("tier")))
                for it in items[:a.limit]]
    labels = json.load(open(os.path.join(D0, "labels.json"), encoding="utf-8"))
    gold = {i["file"]: i["label"] for i in labels["items"]}
    repo = os.path.join(ROOT, labels["target_repo"])
    return [(os.path.join(D0, "reports", f), repo, "%s  (gold %s)" % (why, gold.get(f))) for f, why in SHOWCASE]


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--system", default="b1")
    ap.add_argument("--report")
    ap.add_argument("--repo")
    ap.add_argument("--data", help="a dataset JSONL (D1-D4 shape)")
    ap.add_argument("--id", nargs="*", help="item id(s) from --data")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--showcase", action="store_true", help="one D0 report per tier (the default)")
    ap.add_argument("--skeptic", action="store_true")
    ap.add_argument("--repro", action="store_true")
    ap.add_argument("--json", help="also write the full results here")
    a = ap.parse_args(argv)
    try:
        system = build(a.system)
    except Skipped as e:
        _w(out, "system %s cannot run here: %s" % (a.system, e))
        return 2
    results, workspaces = [], {}
    try:
        for report, repo, title in cases_from_args(a):
            ws = workspaces.setdefault(repo, Workspace(repo))
            res, _ = run_one(system, report, repo, ws)
            sk = skeptic_view(res, report, ws) if a.skeptic else None
            rp = None
            if a.repro:
                clean, _ = ex.sanitize(open(report, encoding="utf-8").read())
                rp = extract_repro(clean, res.get("claims"))
            show(out, res, report, title, sk, rp)
            results.append({"report": report, "result": res, "skeptic": sk, "repro": rp})
    finally:
        for ws in workspaces.values():
            ws.close()
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1, default=str)
        _w(out, "wrote %s" % a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
