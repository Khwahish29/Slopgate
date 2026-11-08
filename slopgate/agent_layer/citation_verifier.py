"""Citation verifier and verdict stage. Deterministic: no model is called here.

The agent's verdict proposer writes {"verdict", "rationale"} from the claims and the ledger.
This module decides what of that survives. agent.finalize() calls it as a hook:

    verdict, text = verify_and_adjudicate(proposed, rationale, ledger, claims, injection)
    verdict, text, events = verify(...)          # same decision, plus the reason for every drop

Per sentence of the rationale (at most MAX_RATIONALE_SENTENCES):

  1. exists      every cited ID (E3, [E3], (E3)) is a row in the ledger. One fake ID makes the
                 whole verdict UNVERIFIED: a model that invents evidence is not trusted on the rest.
  2. cited       a sentence with no citation is dropped (the prompt requires one per fact).
  3. about       every symbol / path / version the sentence names must be something one of its
                 cited rows actually checked (its arguments or its result). Citing E1 for a fact
                 about a different file is a misattribution: dropped.
  4. status      an upper-case tool status quoted in the sentence (ABSENT, DEFINED, MISLOCATED ...)
                 must be the status or evidence class of a cited row: dropped otherwise.
  5. polarity    a sentence that says something is missing / wrong must cite at least one row
                 whose result is negative; one that says it exists must cite a positive row; a
                 definite claim resting only on INCONCLUSIVE / ERROR rows is dropped.

Then the verdict:

  * REPRODUCIBLE never survives: existence checks cannot show that a bug is exploitable.
  * HALLUCINATED survives only if (a) a surviving sentence cites a CONTRADICTION row for a
    load-bearing claim, and (b) the rule adjudicator, re-run on the load-bearing view of the
    ledger, independently says HALLUCINATED.
  * Everything else is UNVERIFIED. The safer verdict always wins.

The text checks are lexical, so they are deliberately one-sided: they can only remove sentences
and downgrade verdicts, never add support. A clumsy but true sentence may be dropped; a
contradicted one should not survive.
"""
import re

from . import agent as ag
from . import verifier
from .ledger import Ledger

MAX_SENTENCES = ag.MAX_RATIONALE_SENTENCES

# raw tool status -> polarity of the fact it establishes (independent of whether it is evidence)
POSITIVE = {"DEFINED", "EXISTS", "LOCATED", "IN_RANGE", "FOUND", "REACHABLE", "PRESENT_IN_HISTORY"}
NEGATIVE = {"ABSENT", "MENTIONED", "NOT_FOUND", "OUT_OF_RANGE", "MISLOCATED", "NOT_DEFINED",
            "NO_SUCH_FILE", "NEVER_IN_HISTORY", "REMOVED", "UNREACHABLE"}
NEUTRAL = {"INCONCLUSIVE", "UNKNOWN", "UNCERTAIN", "N/A", "DECLARED_ONLY"}
STATUS_TOKENS = POSITIVE | NEGATIVE | NEUTRAL | {"GROUND", "CONTRADICTION", "ERROR"}
_STATUS_RE = re.compile(r"(?<![A-Za-z_/])(%s)(?![A-Za-z_])" % "|".join(
    re.escape(s) for s in sorted(STATUS_TOKENS, key=len, reverse=True)))

_HEDGE = re.compile(r"(?i)\b(?:inconclusive|failed|errors?|timed? ?out|timeout|could not|couldn't|uncertain|"
                    r"undetermined|unknown|unresolved|unclear|indirect(?:ly)?|unchecked|not (?:be )?checked)\b")
# a negator and the (up to) two words it governs: "not found in", "never defined", "no definition"
_NEGATION = re.compile(r"(?i)\b(?:not|never|no|cannot|can't|isn't|wasn't|aren't|doesn't|didn't|nowhere|"
                       r"neither|nor|without)\b(?:\s+[\w/.\-]+){0,2}")
_NEG_WORDS = re.compile(r"(?i)\b(?:missing|absent|nonexistent|non-existent|out[- ]of[- ]range|exceeds?|"
                        r"beyond|elsewhere|mislocated|unreachable|removed|deleted|invented|fabricated|"
                        r"hallucinated|contradict\w*|wrong (?:file|path|line|version)|"
                        r"only (?:mentioned|named|appears?|in (?:a |the )?(?:comments?|strings?|docs?|prose)))")
_POS_WORDS = re.compile(r"(?i)\b(?:defined|definition|exists?|present|found|located|resolves?|resolved|"
                        r"reachable|called|confirms?|confirmed|grounded|matches|in range|within)\b")


def stance(sentence):
    """hedge | negative | positive | mixed | neutral. Lexical and conservative by design."""
    if _HEDGE.search(sentence):
        return "hedge"
    neg = bool(_NEGATION.search(sentence) or _NEG_WORDS.search(sentence))
    rest = _NEGATION.sub(" ", sentence)
    pos = bool(_POS_WORDS.search(rest))
    if neg and pos:
        return "mixed"
    return "negative" if neg else "positive" if pos else "neutral"


def polarity(row):
    if "error" in row["result"]:
        return "neutral"
    s = row["status"]
    return "positive" if s in POSITIVE else "negative" if s in NEGATIVE else "neutral"


# --------------------------------------------------------------------------- evidence classes

def rebuild_meta(ledger, claims):
    """{row id: {"claims", "cls", "tool", "auth"}}: what agent.triage keeps in `meta`, recomputed from
    the ledger alone with the agent's own rules (the hook is not handed meta).

    The ref context of each row is the context *before* it ran, as in the loop: a symbol_in_file
    check counts as authoritative only if no claimed tag was pending or unresolvable at that point."""
    na = ag.claim_na(claims)
    pairs = {(sc["value"], pc["value"]) for sc, pc in ag.assoc_pairs(claims, na)}
    meta, prefix = {}, Ledger()
    for r in ledger.rows:
        tool, args = r["tool"], r["args"]
        ctype, key = ag.TOOL_CLAIM_TYPE.get(tool), ag.TOOL_VALUE_ARG.get(tool)
        ids = [c["id"] for c in claims
               if ctype and c["type"] == ctype and c["id"] not in na and key in args and ag._same(c["value"], args[key])]
        auth = ag.ref_ctx(claims, prefix, na, args.get("ref")) in ag.AUTHORITATIVE_CTX
        meta[r["id"]] = {"claims": ids, "cls": ag.classify(tool, r["result"], args, pairs, auth),
                         "tool": tool, "auth": auth}
        prefix.rows.append(r)
    return meta


# --------------------------------------------------------------------------- what a row is about

def _strings(x, out):
    if isinstance(x, str):
        out.add(x)
    elif isinstance(x, dict):
        for v in x.values():
            _strings(v, out)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _strings(v, out)


def row_entities(row):
    """Symbols, paths and versions a row checked or reported: its arguments, plus the locations
    in its result (definition files, homes, resolved tag, nearest tags)."""
    out = set()
    _strings({k: v for k, v in row["args"].items() if k != "ref"}, out)
    res, found = row["result"], set()
    for k in ("location", "path", "tag", "nearest", "version", "claimed", "homes"):
        _strings(res.get(k), found)
    _strings((res.get("loc") or {}).get("homes"), found)
    _strings([d.get("file") for d in (res.get("record") or {}).get("definitions", [])], found)
    for s in found:                     # "chunk_decode <- src/main.c:12" also names src/main.c and chunk_decode
        out.add(s)
        out |= set(_PATHLIKE.findall(s)) | set(re.findall(r"[A-Za-z_]\w{2,80}", s))
    return {e for e in out if len(e) >= 3}


_PATHLIKE = re.compile(r"(?<![\w/.\-])((?:[\w.\-]+/)+[\w\-]+\.[A-Za-z0-9]{1,5})(?![\w/\-])")
_CODELIKE = re.compile(r"`([A-Za-z_]\w{2,80})(?:\(\))?`|\b([A-Za-z_]\w{2,80})\(\)|\b([a-z0-9]+(?:_[a-z0-9]+)+)\b")
NOT_ENTITIES = set(ag.TOOLS) | {"load_bearing", "claim_id", "ref_used", "file_lines"}


def _mentions(sentence, entities):
    """Entities the sentence names: known ones (ledger + claims), plus anything that looks like a
    file path or a code identifier, so a fact about something no tool touched cannot slip through."""
    found = set()
    for e in entities:
        if re.search(r"(?<![\w/.\-])%s(?![\w/\-]|\.[A-Za-z0-9_])" % re.escape(e), sentence):
            found.add(e)
    found |= set(_PATHLIKE.findall(sentence))
    for m in _CODELIKE.finditer(sentence):
        name = next(g for g in m.groups() if g)
        if name not in NOT_ENTITIES and not re.fullmatch(r"[A-Z0-9_]+", name):
            found.add(name)
    # a path also covers its own prefix matches ("lib/a.c" does not count as "a.c")
    return {e for e in found if not any(e != f and e in f and f in found for f in found)}


# --------------------------------------------------------------------------- per-sentence check

def check_sentence(sentence, ledger, universe, cls=None):
    """-> (keep, reason, cites). `universe` is every entity the ledger or the claims name;
    `cls` maps row id -> evidence class (GROUND / CONTRADICTION / INCONCLUSIVE / ERROR)."""
    cites = ag.cited_ids(sentence)
    rows = [ledger.get(c) for c in cites]
    if not cites:
        return False, "no citation", cites
    if any(r is None for r in rows):
        return False, "cites a nonexistent row", cites
    named = _mentions(sentence, universe)
    covered = set().union(*(row_entities(r) for r in rows))
    stray = sorted(named - covered)
    if stray:
        return False, "names %s, which no cited row checked" % ", ".join(stray), cites
    quoted = set(_STATUS_RE.findall(sentence))
    if quoted:
        have = {r["status"] for r in rows} | {"ERROR" for r in rows if "error" in r["result"]}
        have |= {(cls or {}).get(r["id"]) for r in rows} - {None}
        if not quoted & have:
            return False, "quotes status %s but the cited rows say %s" % (
                "/".join(sorted(quoted)), "/".join(sorted(have))), cites
    st, pols = stance(sentence), {polarity(r) for r in rows}
    if st in ("negative", "positive") and pols == {"neutral"}:
        return False, "states a definite %s fact on inconclusive evidence only" % st, cites
    if st == "negative" and "negative" not in pols:
        return False, "says something is missing or wrong, but the cited rows found it", cites
    if st == "positive" and "positive" not in pols:
        return False, "says something exists, but the cited rows found it missing", cites
    if st == "mixed" and pols == {"neutral"}:
        return False, "states definite facts on inconclusive evidence only", cites
    return True, "", cites


def check_rationale(rationale, ledger, claims, meta=None):
    """Per-sentence report: [{"text", "cites", "keep", "reason"}]. Exposed for analysis and tests."""
    meta = meta or rebuild_meta(ledger, claims)
    cls = {k: v["cls"] for k, v in meta.items()}
    universe = set()
    for r in ledger.rows:
        universe |= row_entities(r)
    for c in claims:
        if c["type"] in ("symbol", "path", "tag") and len(str(c["value"])) >= 3:
            universe.add(str(c["value"]))
    out = []
    for i, s in enumerate(ag.split_sentences(rationale)):
        if i >= MAX_SENTENCES:
            out.append({"text": s, "cites": ag.cited_ids(s), "keep": False,
                        "reason": "beyond the %d-sentence limit" % MAX_SENTENCES})
            continue
        keep, why, cites = check_sentence(s, ledger, universe, cls)
        out.append({"text": s, "cites": cites, "keep": keep, "reason": why})
    return out


# --------------------------------------------------------------------------- the hook

def verify_and_adjudicate(proposed, rationale, ledger, claims, injection):
    """The hook agent.finalize() calls: -> (verdict, rationale text), the two values it unpacks.

    If the rationale cites a ledger ID that does not exist, this returns (None, rationale): finalize()
    then runs its own built-in check, which records the bad IDs in finalize_events and forces
    UNVERIFIED. Either way the verdict cannot be HALLUCINATED. Use verify() for the full reasons."""
    verdict, text, events = verify(proposed, rationale, ledger, claims, injection)
    if any(e.startswith("rationale cites nonexistent ledger IDs") for e in events):
        return None, rationale
    return verdict, text


def verify(proposed, rationale, ledger, claims, injection):
    """-> (verdict, rationale text, events). Can only keep or lower the proposed verdict."""
    events = []
    meta = rebuild_meta(ledger, claims)
    report = check_rationale(rationale or "", ledger, claims, meta)
    ids = {r["id"] for r in ledger.rows}
    fake = sorted({c for s in report for c in s["cites"] if c not in ids})
    for n, s in enumerate(report, 1):
        if not s["keep"]:
            events.append("sentence %d dropped: %s" % (n, s["reason"]))
    kept = [s for s in report if s["keep"]]

    verdict = str(proposed).upper() if proposed is not None else "UNVERIFIED"
    if verdict not in ag.VERDICTS:
        events.append("unknown proposed verdict %r: UNVERIFIED" % (proposed,))
        verdict = "UNVERIFIED"
    if fake:
        events.append("rationale cites nonexistent ledger IDs %s: UNVERIFIED" % fake)
        verdict = "UNVERIFIED"
    if not kept:
        events.append("no cited sentences survived: UNVERIFIED")
        verdict = "UNVERIFIED"
    if verdict == "REPRODUCIBLE":
        events.append("REPRODUCIBLE needs execution evidence that no tool provides: UNVERIFIED")
        verdict = "UNVERIFIED"
    if verdict == "HALLUCINATED":
        lb = {c["id"] for c in claims if c["role"] == "load-bearing"}
        anchors = [c for s in kept for c in s["cites"]
                   if meta[c]["cls"] == ag.CONTRADICTION and lb & set(meta[c]["claims"])]
        if not anchors:
            events.append("HALLUCINATED but no surviving sentence cites a load-bearing CONTRADICTION: UNVERIFIED")
            verdict = "UNVERIFIED"
        else:
            lb_claims, view = ag.guard_view(ledger, meta, claims)
            det = verifier.deterministic_verdict(view, lb_claims, injection or [])
            if det["verdict"] != "HALLUCINATED":
                events.append("rule adjudicator on the load-bearing ledger says %s: UNVERIFIED" % det["verdict"])
                verdict = "UNVERIFIED"
            else:
                events.append("HALLUCINATED anchored on %s and confirmed by the rule adjudicator"
                              % ", ".join(sorted(set(anchors))))
    text = " ".join(s["text"] for s in kept) if kept else ag.summary_rationale(ledger, meta, verdict)
    return verdict, text, events
