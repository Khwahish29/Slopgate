"""Deterministic verifier. No model is called here.

A proposed verdict only counts if
  1. every rationale sentence cites ledger rows that exist and support it,
  2. the baseline rule adjudicator, re-run on the same ledger, agrees, and
  3. a HALLUCINATED verdict rests on a tool-confirmed hard contradiction of a
     load-bearing claim.
Anything else becomes UNVERIFIED. The safer verdict always wins.
"""
import re

from . import adjudicate as adj


# ---- ledger -> the structures the unchanged baseline adjudicator expects -----

def primary_claims(claims):
    def first(t):
        c = [x for x in claims if x["type"] == t]
        c.sort(key=lambda x: x["role"] != "load-bearing")
        return c[0]["value"] if c else None
    return {"primary_symbol": first("symbol"), "primary_path": first("path"),
            "line": first("line"), "version": first("tag"), "cwe": first("cwe"),
            "symbols": [c["value"] for c in claims if c["type"] == "symbol"],
            "paths": [c["value"] for c in claims if c["type"] == "path"]}


def ledger_to_grounding(L, claims):
    g = {"symbols": [], "paths": [], "reachability": [],
         "version": {"ref": None, "exists": None, "note": "no version claimed"}}
    seen_s, seen_p = set(), set()
    for r in L.rows:
        res, a = r["result"], r["args"]
        if r["status"] == "INCONCLUSIVE":
            continue                      # a failed check is never evidence
        if r["tool"] == "find_symbol" and a["name"] not in seen_s:
            seen_s.add(a["name"])
            g["symbols"].append(res["record"])
        elif r["tool"] == "check_path" and a["path"] not in seen_p:
            seen_p.add(a["path"])
            g["paths"].append({"path": a["path"], "exists": res["exists"],
                               "line_count": res["line_count"]})
        elif r["tool"] == "check_line_range":
            g["line_check"] = {"claimed": a["line"], "file_lines": res["file_lines"],
                               "in_range": res["in_range"]}
            if a["path"] not in seen_p:
                seen_p.add(a["path"])
                g["paths"].append({"path": a["path"], "exists": res["status"] != "ABSENT",
                                   "line_count": res["file_lines"]})
        elif r["tool"] == "symbol_in_file" and "loc" in res:
            g["symbol_location"] = res["loc"]
        elif r["tool"] == "resolve_tag":
            g["version"] = {"ref": a["version"], "known_tags": res.get("known_tags", []),
                            "exists": {"FOUND": True, "NOT_FOUND": False}.get(res["status"])}
            if res["status"] == "UNKNOWN":
                g["version"]["note"] = res.get("note", "")
        elif r["tool"] == "check_reachability":
            g["reachability"].append({"symbol": a["name"], "result": {
                "reachable": res.get("reachable"), "path": res.get("path"),
                "reason": res.get("reason", "")}})
    return g


def history_for(L, name):
    rows = [r for r in L.find("git_history", name=name) if r["status"] != "INCONCLUSIVE"]
    return rows[0] if rows else None


def deterministic_verdict(L, claims, injection):
    pc = primary_claims(claims)
    out = adj.adjudicate(pc, ledger_to_grounding(L, claims), injection)
    sym = pc["primary_symbol"]
    h = history_for(L, sym) if sym else None
    srow = next((r for r in L.find("find_symbol", name=sym) if r["status"] != "INCONCLUSIVE"), None) if sym else None
    if h and srow and srow["status"] == "ABSENT":
        if h["status"] == "REMOVED":
            c = h["result"]["commits"][0]
            out["verdict"], out["confidence"] = "UNVERIFIED", 0.5
            out["recommended_action"] = "needs human"
            out["reasons"].insert(0, "'%s' is absent at this ref but git history shows it was "
                                     "removed in %s (%s, %s): it existed once, so it is not "
                                     "an invented name" % (sym, c["commit"], c["date"], c["subject"]))
        elif h["status"] == "NEVER_IN_HISTORY":
            out["reasons"].append("git history: '%s' never appears in any commit" % sym)
    return out


# ---- rationale sentences and the citation check --------------------------------


