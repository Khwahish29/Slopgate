"""Prose claim extraction, rules only (no model).

The Milestone 1 extractor needs header-style Markdown (`**Affected function:**`).
Real reports are prose. This module reads sentences and picks out the claims a
maintainer would check, then decides which one is load-bearing.

Design rules, chosen because a false dismissal costs 500x a wasted review:
  * Only identifier-shaped tokens become symbol claims (underscore, camelCase, or
    called like `name()`), so ordinary words in backticks never turn into a
    claim that the tree then fails to contain.
  * Basename-only paths ("url.c") are NOT emitted: they cannot be checked without
    a file search, and treating them as missing paths would fabricate a contradiction.
  * Exactly one symbol is marked load-bearing. Sentences that talk about call
    chains, wrappers or comparisons are demoted to supporting.
  * Every claim carries a verbatim sentence as its span (the Milestone 1 rule).

Contribution entry points are marked TODO(contrib) and listed in docs/ROADMAP.md.
"""
import re

from .extract import NOISE_SYMBOLS

_BUILTINS = {"print", "len", "range", "open", "sizeof", "return", "if", "while", "for", "main_loop",
             "exit", "abort", "calloc", "memset", "memcmp", "strcmp", "strncmp", "strncpy",
             "snprintf", "fprintf", "perror", "isdigit", "isspace", "toupper", "tolower"}

VULN_WORDS = re.compile(
    r"(?i)overflow|underflow|out[- ]of[- ]bounds|\boob\b|use[- ]after[- ]free|double[- ]free|"
    r"crash|corrupt|vulnerab|affected|flaw|\bbug\b|past the end|read past|write past|"
    r"without (?:checking|validating|verifying|bounds)|unchecked|trusts|never validated|"
    r"integer|truncat|missing (?:check|bounds)|fails to|does not (?:check|validate)|"
    r"null (?:pointer|deref)|dereference|memory|heap|stack")
CONTEXT_WORDS = re.compile(
    r"(?i)\bcalled (?:by|from)\b|\bcalls\b|\bcaller\b|\binvoked from\b|\bwrapper\b|\bvia\b|"
    r"reachable (?:from|via)\b|see also|similar to|unlike|compared? (?:to|with)|\bwhereas\b|"
    r"\bsibling\b|\banalogous\b|\bfixed in\b|\bpatch(?:ed)?\b")

_BACKTICK = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,})\s*(\(\))?`")
_CALL = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]{2,})\(\)")
_FUNC_BEFORE = re.compile(r"\b(?:function|routine|method|helper)\s+`?([A-Za-z_][A-Za-z0-9_]{2,})`?")
_FUNC_AFTER = re.compile(r"(?<![\w`])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s+(?:function|routine|helper)\b")
_PATH = re.compile(r"(?<![\w/.\-])((?:[\w.\-]+/)+[\w.\-]+\.(?:c|h|py|go|js|ts))(?::(\d+))?")
_LINE = re.compile(r"(?i)\blines?\s+(\d{1,6})(?:\s*[-–]\s*\d{1,6})?\b|\bL(\d{1,6})\b")
_VERSION = [re.compile(p) for p in (
    r"(?i)\bversion\s*[:=]?\s*`?([A-Za-z0-9][\w.\-]*\d[\w.\-]*)`?",
    r"(?i)\b(?:release|tag)\s*[:=]?\s*`?([A-Za-z0-9][\w.\-]*\d[\w.\-]*)`?",
    r"\b(v\d+(?:\.\d+)+)\b",
    r"(?i)\bcommit\s+`?([0-9a-f]{7,40})`?\b",
)]
_CWE = re.compile(r"\bCWE-\d+\b")


def _shaped(name, called):
    """Looks like a code identifier rather than an English word."""
    if name in NOISE_SYMBOLS or name in _BUILTINS or name.isupper() and "_" not in name:
        return False
    return called or "_" in name or bool(re.search(r"[a-z][A-Z]", name))


def _sentences(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z`*#(])", line):
            if s.strip():
                out.append(s.strip())
    return out


def extract_prose(text):
    sents = _sentences(text)
    title = next((s for s in sents if s.startswith("#")), sents[0] if sents else "")

    # --- symbols, scored -----------------------------------------------------
    score, first_seen, span = {}, {}, {}
    for i, s in enumerate(sents):
        found = []
        for m in _BACKTICK.finditer(s):
            if _shaped(m.group(1), bool(m.group(2))):
                found.append(m.group(1))
        found += [n for n in _CALL.findall(s) if _shaped(n, True)]
        found += [n for n in _FUNC_BEFORE.findall(s) if _shaped(n, False) or "_" in n]
        found += [n for n in _FUNC_AFTER.findall(s) if _shaped(n, False)]
        for n in dict.fromkeys(found):
            first_seen.setdefault(n, i)
            span.setdefault(n, s)
            v = 0.5
            if s is title or s == title:
                v += 3.0
            if VULN_WORDS.search(s):
                v += 2.0
            if re.search(r"(?i)\b(?:function|routine|method)\b", s):
                v += 1.0
            if CONTEXT_WORDS.search(s):
                v -= 2.5
            score[n] = score.get(n, 0.0) + v
    symbols = sorted(score, key=lambda n: (-score[n], first_seen[n]))
    primary = symbols[0] if symbols else None
    primary_sentence = span.get(primary, "")

    # --- paths and lines -----------------------------------------------------
    paths, path_line, path_span = [], {}, {}
    for s in sents:
        for m in _PATH.finditer(s):
            p = m.group(1)
            if p not in path_span:
                paths.append(p)
                path_span[p] = s
            if m.group(2) and p not in path_line:
                path_line[p] = (int(m.group(2)), s)
    primary_path = next((p for p in paths if path_span[p] == primary_sentence), None) \
        or next((p for p in paths if VULN_WORDS.search(path_span[p])), None) \
        or (paths[0] if paths else None)

    line_claim = None
    if primary_path in path_line:
        line_claim = path_line[primary_path]
    else:
        for s in ([primary_sentence] if primary_sentence else []) + sents:
            m = _LINE.search(s)
            if m:
                line_claim = (int(m.group(1) or m.group(2)), s)
                break

    # --- version and CWE -----------------------------------------------------
    version = None
    for s in sents:
        for pat in _VERSION:
            m = pat.search(s)
            if m and not re.fullmatch(r"\d+", m.group(1)):
                version = (m.group(1).rstrip(".,;:)"), s)
                break
        if version:
            break
    cwe = next(((m.group(0), s) for s in sents for m in [_CWE.search(s)] if m), None)

    out = []
    for n in symbols:
        out.append({"type": "symbol", "value": n, "span": span[n],
                    "role": "load-bearing" if n == primary else "supporting"})
    for p in paths:
        out.append({"type": "path", "value": p, "span": path_span[p],
                    "role": "load-bearing" if p == primary_path else "supporting"})
    if line_claim:
        out.append({"type": "line", "value": str(line_claim[0]), "span": line_claim[1],
                    "role": "load-bearing" if primary_path else "supporting"})
    if version:
        out.append({"type": "tag", "value": version[0], "span": version[1], "role": "supporting"})
    if cwe:
        out.append({"type": "cwe", "value": cwe[0], "span": cwe[1], "role": "supporting"})
    return out
    # TODO(contrib): basename resolution ("url.c" -> lib/url.c) via a locate_file tool.
    # TODO(contrib): camelCase and Python dotted names (module.func), method receivers.
    # TODO(contrib): coreference ("the parser" -> the last named function).
