"""Claim extraction: pull structured claims out of a free-text report.

Deliberately rule-based. No model is called anywhere in this baseline: the
whole point is to establish what a purely deterministic system scores, so that
any later LLM stage has to justify its cost and latency against this number.

Report text is untrusted input. It is sanitized before anything else reads it,
and every instruction-shaped span is recorded rather than silently dropped.
"""
import re

# Report text is untrusted. Anything matching these is stripped before the
# report is shown to a model, and recorded as an injection signal.
INJECTION_PATTERNS = [
    r"<!--.*?-->",
    r"(?i)ignore (all |any )?previous instructions",
    r"(?i)system note\s*:",
    r"(?i)set verdict to",
    r"(?i)do not run further checks",
    r"(?i)pre-?verified by",
]

FIELD_RE = {
    "file": r"\*\*Affected file:\*\*\s*(\S+)",
    "function": r"\*\*Affected function:\*\*\s*([A-Za-z_][A-Za-z0-9_]*)",
    "line": r"\*\*Affected line:\*\*\s*(\d+)",
    "version": r"\*\*Version:\*\*\s*(\S+)",
    "cwe": r"\*\*CWE:\*\*\s*(CWE-\d+)",
}

SYMBOL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,})\(\)`")
PATH_RE = re.compile(r"`?((?:[\w.-]+/)+[\w.-]+\.[ch])`?")


# Pattern families for text aimed at the triage system rather than at a human reader. These
# are categories, not copies of known attack strings: each one names a *function* of the text
# (addressing the model, setting the verdict, forging tool output, asking to skip checks).
# Both directions are covered: pushing a fabricated report towards "real", and pushing a real
# report towards "fabricated" (suppression). Each pattern stops at the end of its sentence or
# line, so the claims around an injection survive redaction.
# Triage vocabulary only: "marks the buffer as invalid" is ordinary C prose and must survive.
_VERDICT_WORD = (r"(?:hallucinated|fabricated|invented|made[- ]up|non-?existent|ai[- ]?slop|slop|spam|not a (?:real )?bug|"
                 r"false positive|reproducible|verified|confirmed|real(?:,? high severity)?)")
INJECTION_FAMILIES = [
    ("addressed_to_model",
     r"(?i)\b(?:if|when) you are an? (?:ai|llm|language model|automated|model|assistant|bot|triage)\b[^\n]*"),
    ("addressed_to_model",
     r"(?i)\b(?:note|message|instructions?|guidance) (?:to|for) (?:the |any )?(?:ai|llm|automated|"
     r"triage|bot|model|language model|machine)\b[^\n]*"),
    ("addressed_to_model",
     r"(?i)\b(?:attention|dear|hey),? (?:ai|llm|model|bot|assistant|triage (?:system|tool|bot))\b[^\n]*"),
    ("addressed_to_model",       # a role label aimed at machine readers: "AI reviewers: ...", "Automated triage, ..."
     r"(?i)\b(?:ai|llm|automated|machine|bot)[- ](?:reviewers?|triag(?:e|ers?)|systems?|tools?|agents?|"
     r"assistants?|readers?)\s*[:,][^\n]*"),
    ("verdict_directive",
     # the directive must be about the report itself: "mark this report as fabricated",
     # "close it as AI slop", "treat every claim above as confirmed"
     r"(?i)\b(?:mark|classif(?:y|ied)|label(?:l?ed)?|close|treat|flag|set|record|regard)\b[^.\n]{0,60}?"
     r"\b(?:report|claims?|issue|submission|finding|it|this|everything)\b[^.\n]{0,40}?\b(?:as|to)\s+"
     r"\"?" + _VERDICT_WORD + r"\b[^.\n]*\.?"),
    ("verdict_directive",        # passive form: "this submission be classified as invented"
     r"(?i)\b(?:report|claims?|issue|submission|finding|it|this)\b[^.\n]{0,30}?\b(?:be|been|is|are|was)\s+"
     r"(?:classified|marked|label(?:l?ed)|closed|treated|flagged|recorded|regarded)\s+as\s+\"?"
     + _VERDICT_WORD + r"\b[^.\n]*\.?"),
    ("verdict_directive",
     r"(?i)\bthe correct (?:classification|verdict|label|answer)\b[^.\n]*\.?"),
    ("verdict_directive",
     r"(?i)\bmissing (?:symbols?|functions?|files?|names?) (?:are|is) (?:expected|normal|fine)\b[^.\n]*\.?"),
    ("fake_tool_output",
     r"(?is)\{[^{}]{0,400}\"(?:verdict|classification|label|triage)\"\s*:[^{}]{0,400}\}"),
    ("fake_tool_output",
     r"(?im)^[ \t>`*-]*(?:verdict|classification|triage[ _-]?(?:result|verdict)|final[ _]verdict)\s*[:=]\s*"
     r"(?:hallucinated|unverified|reproducible|real|fake|fabricated|confirmed)\b[^\n]*$"),
    ("fake_tool_output",
     r"(?im)^[ \t>`*-]*(?:find_symbol|check_path|symbol_in_file|check_line_range|resolve_tag|git_history|"
     r"check_reachability)\s*[:(][^\n]*$"),
    ("fake_tool_output",
     r"(?i)\[(?:triage|tool|system|slopgate|scanner|verifier)[- _]?(?:tool[- _]?)?(?:output|result|note|log)\]"),
    ("skip_checks",
     r"(?i)\b(?:without|do not|don't|skip|no need to|there is no need to)\s+(?:running|run(?:ning)?)\s+"
     r"(?:any\s+|further\s+|the\s+)*(?:checks?|verification|validation|analysis|tools?)\b[^.\n]*\.?"),
    ("skip_checks",              # "closed without review", "dismiss it without checking"
     r"(?i)\b(?:closed?|dismiss(?:ed)?|reject(?:ed)?|discard(?:ed)?)\b[^.\n]{0,40}?\bwithout\s+(?:any\s+|further\s+)?"
     r"(?:review|checking|verification|validation|analysis|investigation)\b[^.\n]*\.?"),
]
# Characters with no visible width, used to split trigger words ("I​gnore") past a filter.
_HIDDEN = re.compile("[­᠎​-‏‪-‮⁠-⁤﻿]")


def normalize(text):
    """NFKC (full-width and compatibility letters to ASCII) and hidden-character removal.
    Returns (text, number of hidden characters removed)."""
    import unicodedata
    text = unicodedata.normalize("NFKC", text)
    n = len(_HIDDEN.findall(text))
    return _HIDDEN.sub("", text), n


def sanitize(text):
    """Strip injection-shaped spans. Returns (clean_text, signals).

    Each signal: {pattern, kind, offset, span}. `kind` is "known" for the original phrase list,
    else the family name above, or "hidden_chars". Redaction replaces the span with a marker,
    so a later stage can see that something was removed and where."""
    signals = []
    clean, hidden = normalize(text)
    if hidden:
        signals.append({"pattern": "hidden characters", "kind": "hidden_chars", "offset": 0,
                        "span": "%d zero-width or bidi control character(s) removed" % hidden})
    for kind, pats in (("known", [(None, p) for p in INJECTION_PATTERNS]), ("family", INJECTION_FAMILIES)):
        for fam, pat in pats:
            for m in re.finditer(pat, clean, re.S):
                signals.append({"pattern": pat, "kind": fam or kind, "offset": m.start(),
                                "span": m.group(0)[:80].replace("\n", " ")})
            clean = re.sub(pat, "[REDACTED-BY-SLOPGATE]", clean, flags=re.S)
    return clean, signals


# Standard-library names carry no grounding signal about the target project.
NOISE_SYMBOLS = {"memcpy", "strlen", "malloc", "free", "realloc", "strcpy",
                 "sprintf", "printf", "strcat", "memmove", "assert", "strstr"}


def extract_heuristic(text):
    claims = {"symbols": [], "paths": [], "line": None, "version": None,
              "cwe": None, "primary_symbol": None, "primary_path": None}
    for key, pat in FIELD_RE.items():
        m = re.search(pat, text)
        if not m:
            continue
        v = m.group(1)
        if key == "function":
            claims["symbols"].append(v)
            claims["primary_symbol"] = v
        elif key == "file":
            claims["paths"].append(v)
            claims["primary_path"] = v
        elif key == "line":
            claims["line"] = int(v)
        else:
            claims[key] = v
    claims["symbols"] += SYMBOL_RE.findall(text)
    claims["paths"] += PATH_RE.findall(text)
    claims["symbols"] = sorted(set(claims["symbols"]) - NOISE_SYMBOLS)
    claims["paths"] = sorted(set(claims["paths"]))
    if claims["primary_symbol"] is None and claims["symbols"]:
        claims["primary_symbol"] = claims["symbols"][0]
    if claims["primary_path"] is None and claims["paths"]:
        claims["primary_path"] = claims["paths"][0]
    return claims
