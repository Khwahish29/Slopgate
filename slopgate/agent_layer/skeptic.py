"""Skeptic pass: try to break a HALLUCINATED verdict before it is accepted.

Auto-closing a real vulnerability costs 500x a wasted human review
(adjudicate.COST), so a HALLUCINATED verdict gets one adversarial pass. The
skeptic looks for the innocent explanations of each contradiction and runs the
tool calls that would reveal them:

  completed   the verdict rests on a check that actually finished (not INCONCLUSIVE)
  history     an ABSENT/MENTIONED symbol that git history shows was removed or once present
  ref_drift   a symbol or file absent at the resolved ref but present in the working tree
  code_use    a MENTIONED symbol used in code (macro, function pointer, external API)
  model       optional: a model proposes up to N extra checks; only their tool results count

Hard rules:
  * The skeptic can only downgrade HALLUCINATED -> UNVERIFIED. It never upgrades,
    and it never touches UNVERIFIED or REPRODUCIBLE verdicts.
  * An objection counts only if it cites ledger rows produced by tools. Model
    prose alone changes nothing.
  * Every row it adds is tagged by="skeptic", so traces can separate its work
    from the planner's.

Interface for the agent loop:

    out = skeptic_pass(ws, ledger, claims, proposed, injection, backend=None)
    out["verdict"], out["confidence"], out["upheld"], out["objections"], out["rows"]

`proposed` is the dict from verifier.deterministic_verdict (or any dict with
verdict / confidence / reasons).
"""
import json

from . import verifier
from .tools import TOOLS, run_tool

MAX_MODEL_CHECKS = 3


def _primary(claims, t):
    c = [x for x in claims if x["type"] == t]
    c.sort(key=lambda x: x["role"] != "load-bearing")
    return c[0]["value"] if c else None


def _done(rows):
    return [r for r in rows if r["status"] != "INCONCLUSIVE"]


def _resolved_ref(L):
    for r in L.rows:
        if r["tool"] == "resolve_tag" and r["result"].get("tag"):
            return r["result"]["tag"]
    return None


def _run(ws, L, tool, args):
    return L.add(tool, args, run_tool(ws, tool, args), by="skeptic")


def _rule_checks(ws, L, claims):
    """Deterministic objections. Returns a list of {rule, text, cites}."""
    objections = []
    sym, path = _primary(claims, "symbol"), _primary(claims, "path")
    ref = _resolved_ref(L)

    sym_rows = _done(L.find("find_symbol", name=sym)) if sym else []
    path_rows = _done(L.find("check_path", path=path)) if path else []
    srow = sym_rows[0] if sym_rows else None
    prow = path_rows[0] if path_rows else None

    # completed: the primary claims were actually checked
    if sym and not srow and not prow:
        all_rows = L.find("find_symbol", name=sym)
        objections.append({"rule": "completed", "cites": [r["id"] for r in all_rows],
                           "text": "no completed check of the primary symbol '%s'; a failed "
                                   "tool call is not evidence of absence" % sym})
        return objections

    sstatus = srow["status"] if srow else None

    # history: absent or mention-only now, but present in some commit
    if sym and sstatus in ("ABSENT", "MENTIONED"):
        h = _done(L.find("git_history", name=sym))
        h = h[0] if h else _run(ws, L, "git_history", {"name": sym})
        if h["status"] in ("REMOVED", "PRESENT_IN_HISTORY"):
            c = (h["result"].get("commits") or [{}])[0]
            objections.append({"rule": "history", "cites": [srow["id"], h["id"]],
                               "text": "'%s' is %s at this ref but appears in git history (%s %s): "
                                       "a real, since-changed name, not an invented one"
                                       % (sym, sstatus, c.get("commit", "?"), c.get("kind", ""))})

    # ref_drift: absent at the resolved ref, present in the working tree
    if ref:
        if sym and sstatus == "ABSENT":
            w = _run(ws, L, "find_symbol", {"name": sym})
            if w["status"] == "DEFINED":
                objections.append({"rule": "ref_drift", "cites": [srow["id"], w["id"]],
                                   "text": "'%s' is absent at %s but defined in the working tree; "
                                           "the report may target another version" % (sym, ref)})
        if prow and prow["status"] == "ABSENT":
            w = _run(ws, L, "check_path", {"path": path})
            if w["status"] == "EXISTS":
                objections.append({"rule": "ref_drift", "cites": [prow["id"], w["id"]],
                                   "text": "'%s' is absent at %s but exists in the working tree"
                                           % (path, ref)})

    # code_use: MENTIONED but used as code, so the definition scan may simply have missed it
    if srow and sstatus == "MENTIONED":
        rec = srow["result"].get("record", {})
        if rec.get("code_mentions", 0) > 0:
            objections.append({"rule": "code_use", "cites": [srow["id"]],
                               "text": "'%s' has no definition the scanner recognises but is used in "
                                       "code %d time(s): likely a macro, function pointer or external "
                                       "API rather than an invented name" % (sym, rec["code_mentions"])})
    return objections


MODEL_INSTR = (
    "You are the skeptic in a vulnerability-report triage tool. The current verdict is "
    "HALLUCINATED: the tool believes the report cites code that does not exist. Your job is to "
    "find an innocent explanation (renamed or moved code, another version, a macro, a header "
    "declaration, a typo of a real name) and propose at most %d tool calls that would reveal it. "
    "Available tools and argument schemas: %s. Reply as JSON: "
    '{"objection": "<one sentence>", "checks": [{"tool": "<name>", "args": {...}}]}. '
    "Propose no checks if you see no innocent explanation. You cannot set the verdict.")


def _model_checks(ws, L, claims, proposed, backend, limit):
    ask = getattr(backend, "_ask", None)
    if ask is None or limit <= 0:
        return [], 0
    schemas = {k: v[1]["properties"] for k, v in TOOLS.items()}
    payload = json.dumps({
        "claims": [{"type": c["type"], "value": c["value"], "role": c["role"]} for c in claims],
        "ledger": [{"id": r["id"], "tool": r["tool"], "args": r["args"], "status": r["status"]}
                   for r in L.rows],
        "verdict": proposed.get("verdict"), "reasons": proposed.get("reasons", [])[:4]})
    client = getattr(backend, "client", None)
    c0 = getattr(client, "calls", 0)
    try:
        reply = ask(MODEL_INSTR % (limit, json.dumps(schemas)), "<case>\n%s\n</case>" % payload)
        checks = reply.get("checks") or []
        objection = str(reply.get("objection", ""))[:300]
    except Exception:  # noqa: BLE001  (model failure: skip the model step, keep the rule result)
        return [], getattr(client, "calls", 0) - c0
    rows = []
    for chk in checks[:limit]:
        if not isinstance(chk, dict) or chk.get("tool") not in TOOLS:
            continue
        args = chk.get("args") if isinstance(chk.get("args"), dict) else {}
        if any(r["tool"] == chk["tool"] and r["args"] == args for r in _done(L.rows)):
            continue                                   # already answered; no duplicate calls
        rows.append(_run(ws, L, chk["tool"], args))
    out = []
    if rows and objection:
        out.append({"rule": "model", "cites": [r["id"] for r in rows], "text": objection,
                    "advisory": True})            # prose is advisory; the re-adjudication decides
    return out, getattr(client, "calls", 0) - c0


def skeptic_pass(ws, L, claims, proposed, injection=(), backend=None,
                 max_model_checks=MAX_MODEL_CHECKS):
    """Challenge a HALLUCINATED verdict. Mutates L (appends skeptic rows)."""
    n0 = len(L.rows)
    base = {"verdict": proposed["verdict"], "confidence": proposed.get("confidence", 0.0),
            "upheld": True, "objections": [], "rows": [], "model_calls": 0,
            "reasons": list(proposed.get("reasons", []))}
    if proposed["verdict"] != "HALLUCINATED":
        return base

    objections = _rule_checks(ws, L, claims)
    model_obj, mcalls = _model_checks(ws, L, claims, proposed, backend, max_model_checks) \
        if backend is not None else ([], 0)
    objections += model_obj

    # Re-adjudicate on the extended ledger: new tool facts can move the rule verdict.
    det = verifier.deterministic_verdict(L, claims, list(injection))
    binding = [o for o in objections if not o.get("advisory")]
    out = dict(base, objections=objections, rows=[r["id"] for r in L.rows[n0:]], model_calls=mcalls)
    if binding or det["verdict"] != "HALLUCINATED":
        out.update(verdict="UNVERIFIED", upheld=False,
                   confidence=min(0.5, det.get("confidence", 0.5)),
                   reasons=["skeptic: " + o["text"] for o in binding] + det["reasons"])
    else:
        out.update(confidence=det["confidence"], reasons=det["reasons"])
    return out
