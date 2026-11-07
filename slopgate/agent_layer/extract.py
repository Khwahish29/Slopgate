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


def sanitize(text):
    """Strip injection-shaped spans. Returns (clean_text, signals)."""
    signals = []
    clean = text
    for pat in INJECTION_PATTERNS:
        for m in re.finditer(pat, clean, re.S):
            signals.append({"pattern": pat, "offset": m.start(),
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
