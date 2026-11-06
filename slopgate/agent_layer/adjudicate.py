"""Adjudication.

Deliberately NOT an averaged score. The operating point comes from an explicit
cost matrix: auto-closing a real vulnerability is treated as 500x worse than
wasting one human review, so the agent abstains (UNVERIFIED) unless the
evidence for HALLUCINATED is unambiguous.

The LLM never sees the report as instructions and never sets the verdict on its
own; in llm mode it only supplies a rationale over the already-computed
evidence table.
"""

COST = {"false_hallucinated": 500.0, "false_reproducible": 1.0, "abstain": 0.2}


def adjudicate(claims, grounding, injection_signals):
    ev, verdict, conf, reasons = [], None, 0.0, []

    syms = grounding["symbols"]
    absent = [s for s in syms if s["status"] == "ABSENT"]
    mention_only = [s for s in syms if s["status"] == "MENTIONED"]
    defined = [s for s in syms if s["status"] == "DEFINED"]

    for s in syms:
        ev.append({
            "type": "symbol", "value": s["symbol"], "status": s["status"],
            "checked_by": s["checked_by"],
            "evidence": "%d definition(s), %d mention(s) (%d in code) across %d files"
                        % (len(s["definitions"]), s["mention_count"],
                           s["code_mentions"], s["files_searched"]),
        })
    for p in grounding["paths"]:
        ev.append({"type": "path", "value": p["path"], "status":
                   "EXISTS" if p["exists"] else "ABSENT",
                   "checked_by": "filesystem stat",
                   "evidence": "%d lines" % p["line_count"] if p["exists"]
                               else "not present at this ref"})
    v = grounding["version"]
    ev.append({"type": "version", "value": v.get("ref"),
               "status": {True: "EXISTS", False: "ABSENT", None: "UNKNOWN"}[v.get("exists")],
               "checked_by": "git tag --list",
               "evidence": v.get("note") or "tags: %s" % ", ".join(v.get("known_tags", []))})
    line = grounding.get("line_check")
    if line:
        ev.append({"type": "line", "value": line["claimed"],
                   "status": "IN_RANGE" if line["in_range"] else "OUT_OF_RANGE",
                   "checked_by": "line count of claimed file",
                   "evidence": "file has %d lines" % line["file_lines"]})
    loc = grounding.get("symbol_location")
    if loc:
        ev.append({"type": "location", "value": "%s in %s"
                                                % (loc["symbol"], loc["claimed"]),
                   "status": loc["status"],
                   "checked_by": "definition site vs claimed file",
                   "evidence": "defined in %s" % ", ".join(loc["homes"])})
    for r in grounding.get("reachability", []):
        ev.append({"type": "reachability", "value": r["symbol"],
                   "status": {True: "REACHABLE", False: "UNREACHABLE",
                              None: "N/A"}[r["result"].get("reachable")],
                   "checked_by": "caller graph, depth 4",
                   "evidence": r["result"].get("path") or r["result"].get("reason", "")})

    for s in injection_signals:
        ev.append({"type": "injection", "value": s["pattern"], "status": "STRIPPED",
                   "checked_by": "pre-adjudication sanitizer",
                   "evidence": "offset %d: %s" % (s["offset"], s["span"])})

    # --- rules, keyed on the report's OWN declared primary claim ---------
    pname = claims.get("primary_symbol")
    primary = next((s for s in syms if s["symbol"] == pname), None)
    pstatus = primary["status"] if primary else None
    preach = next((r["result"] for r in grounding.get("reachability", [])
                   if r["symbol"] == pname), {})
    ppath = next((p for p in grounding["paths"]
                  if p["path"] == claims.get("primary_path")), None)

    if pstatus == "ABSENT":
        verdict, conf = "HALLUCINATED", 0.95
        reasons.append("the report's own declared vulnerable function '%s' does "
                       "not appear anywhere in the tree at this ref" % pname)
    elif pstatus == "MENTIONED":
        verdict, conf = "HALLUCINATED", 0.88
        reasons.append("'%s' appears only inside a comment or prose, never as a "
                       "definition; a grep-based check would have reported it as "
                       "present" % pname)
    elif ppath is not None and not ppath["exists"]:
        verdict, conf = "HALLUCINATED", 0.85
        reasons.append("claimed file '%s' does not exist at this ref"
                       % claims.get("primary_path"))
    elif loc and loc["status"] == "MISLOCATED":
        verdict, conf = "HALLUCINATED", 0.90
        reasons.append("'%s' is defined in %s, not in the claimed file '%s', "
                       "which does not contain the symbol at all; the symbol, "
                       "the path and the line all check out individually and "
                       "only their association is false"
                       % (pname, ", ".join(loc["homes"]), loc["claimed"]))
    elif preach.get("reachable") is False:
        verdict, conf = "UNVERIFIED", 0.60
        reasons.append("'%s' is defined but no call path reaches it from a "
                       "non-test entry point; possible dead code, routed to a "
                       "human rather than closed" % pname)
    elif pstatus == "DEFINED":
        verdict, conf = "UNVERIFIED", 0.50
        reasons.append("every claim grounds to real, reachable code; existence "
                       "checks cannot decide exploitability - needs PoC "
                       "execution, which the baseline does not implement")
    else:
        verdict, conf = "UNVERIFIED", 0.30
        reasons.append("no checkable primary claim extracted")

    line = grounding.get("line_check")
    if line and not line["in_range"]:
        reasons.append("claimed line %d exceeds the %d lines in the claimed file"
                       % (line["claimed"], line["file_lines"]))
        if verdict == "HALLUCINATED":
            conf = min(0.97, conf + 0.05)
    if absent and pstatus not in ("ABSENT", "MENTIONED"):
        reasons.append("%d secondary symbol(s) also unresolved: %s"
                       % (len(absent), ", ".join(s["symbol"] for s in absent)))
    if grounding["version"].get("exists") is False:
        reasons.append("claimed version ref is not a known tag")

    if injection_signals and verdict == "HALLUCINATED":
        conf = min(0.99, conf + 0.03)
        reasons.append("report contains %d instruction-shaped span(s) aimed at "
                       "the triage system itself" % len(injection_signals))
    elif injection_signals:
        verdict = "UNVERIFIED"
        reasons.append("report attempts to steer the triage system; routed to a "
                       "human regardless of grounding outcome")

    action = {"HALLUCINATED": "deprioritize with evidence bundle attached",
              "UNVERIFIED": "needs human",
              "REPRODUCIBLE": "escalate"}[verdict]

    return {"verdict": verdict, "confidence": round(conf, 2),
            "recommended_action": action, "reasons": reasons, "claims": ev,
            "cost_model": COST}
