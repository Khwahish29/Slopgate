"""Prose claim extractor: deterministic, no model.

The header extractor in extract.py only reads `**Affected function:**`-style
fields. Real reports are mostly prose ("the overflow is in parse_chunk() in
lib/http_chunks.c around line 214, tested on curl 8.4.0"), so this module pulls
the same five claim types out of free text:

    symbol  path  line  tag  cwe

Output uses the schema llm.validate_claims checks (type, value, span, role).
Every span is a verbatim substring of the report and contains the value, so
these claims pass the same verbatim-span rule a model's claims must pass.

Role assignment: a claim is load-bearing if the vulnerability cannot exist
unless it is true. Header fields win when present; otherwise the primary symbol
is the one the report ties to the defect most strongly (title, defect-word
sentences, "in X()" phrasing), and the primary path is the one that sits next to
it.
"""
import re

from . import extract as ex

# ---- segmentation ----------------------------------------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*#(\[])")


def segments(text):
    """Lines, then sentences inside each line. Each segment is verbatim text."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for s in _SENT_SPLIT.split(line):
            s = s.strip()
            if s:
                out.append(s)
    return out


# ---- patterns --------------------------------------------------------------

DEFECT_WORDS = re.compile(
    r"(?i)overflow|out[- ]of[- ]bounds|use[- ]after[- ]free|double[- ]free|null[- ]pointer|"
    r"null dereference|underflow|uninitiali[sz]ed|memory leak|race condition|"
    r"write[s]? past|read[s]? past|beyond the|injection|vulnerab|crash|corrupt|"
    r"trusts? a length|unchecked|without (?:bounds )?check")

CODE_EXT = r"(?:c|h|cc|cpp|cxx|hpp|py|go|js|ts|rs|java|rb|php)"
PATH_RE = re.compile(r"(?<![\w/.:-])((?:[\w.-]+/)+[\w.-]+\.%s)(?::(\d+))?(?![\w/])" % CODE_EXT)

# foo() / foo(...) ; backticked or bare
CALL_RE = re.compile(r"`?\b([A-Za-z_]\w{2,80})\s*\((?:[^()]{0,60})\)`?")
# "function foo", "the foo function", "routine foo", "helper `foo`"
KEYWORD_SYM_RES = [   # separate passes: one form must not consume the other's text
    re.compile(r"(?i)\b(?:function|routine|method|helper|callback|handler)\s+`?([A-Za-z_]\w{2,80})`?"),
    re.compile(r"(?i)`?\b([A-Za-z_]\w{2,80})`?\s+(?:function|routine|helper|callback)\b"),
]
BACKTICK_RE = re.compile(r"`([A-Za-z_]\w{2,80})`")

LINE_RES = [
    re.compile(r"(?i)\blines?\s+(?:number\s+)?(\d{1,6})\b"),
    re.compile(r"\bL(\d{1,6})\b"),
]
TAG_RES = [
    re.compile(r"(?i)\b(?:version|release|tag(?:ged)?|tested on|affects?|in)\s*:?\s*\**\s*"
               r"(v?\d+(?:[._]\d+){1,3}(?:[-.]?(?:rc|beta|alpha)\d*)?)\b"),
    re.compile(r"\b([A-Za-z][A-Za-z0-9]*-\d+(?:[._]\d+)+)\b"),          # curl-8_4_0, minihttp-1_0
    re.compile(r"(?i)\bcommit\s+`?([0-9a-f]{7,40})\b"),
    re.compile(r"(?i)\b[a-z][\w-]*\s+(v?\d+\.\d+(?:\.\d+)?)\b"),         # "curl 8.4.0"
]
CWE_RE = re.compile(r"\bCWE-\d{1,5}\b")

NOT_SYMBOLS = {
    "if", "for", "while", "switch", "return", "sizeof", "else", "case", "void", "char",
    "int", "long", "unsigned", "struct", "static", "const", "the", "and", "with", "see",
    "this", "that", "from", "into", "via", "when", "which", "also", "only", "e.g", "i.e",
    "note", "example", "line", "lines", "file", "function", "version", "commit",
}


def _is_identifier_like(name, backticked):
    """Bare prose words are not symbols. Require code-ish shape unless the
    author put the name in backticks."""
    if name.lower() in NOT_SYMBOLS or name in ex.NOISE_SYMBOLS:
        return False
    if re.fullmatch(r"[A-Z0-9_]+", name):            # ALL_CAPS: a macro or constant, not a function
        return False
    if name.upper().startswith("CWE"):
        return False
    if backticked:
        return True
    return "_" in name or bool(re.search(r"[a-z][A-Z]", name)) or bool(re.search(r"\d", name))


# ---- extraction ------------------------------------------------------------

def _header_fields(text):
    out = {}
    for key, pat in ex.FIELD_RE.items():
        m = re.search(pat, text)
        if m:
            out[key] = m.group(1)
    return out


def _symbols(segs):
    """name -> {'span': first segment, 'score': int, 'first': index}"""
    found = {}

    def hit(name, i, seg, bonus, backticked):
        if not _is_identifier_like(name, backticked):
            return
        rec = found.setdefault(name, {"span": seg, "score": 0, "first": i})
        rec["score"] += 1 + bonus

    for i, seg in enumerate(segs):
        title = seg.startswith("#") or i == 0
        defect = bool(DEFECT_WORDS.search(seg))
        base = (3 if title else 0) + (2 if defect else 0)
        for m in CALL_RE.finditer(seg):
            name = m.group(1)
            pre = seg[max(0, m.start() - 4):m.start()].lower()
            bonus = base + (2 if pre.strip().endswith("in") else 0)
            # `foo()` or foo() is a call shape; "overrun (see below)" is prose
            tight = m.group(0).startswith("`") or seg[m.start(1) + len(name)] == "("
            hit(name, i, seg, bonus, tight)
        for rx in KEYWORD_SYM_RES:
            for m in rx.finditer(seg):
                hit(m.group(1), i, seg, base + 2, "`" in m.group(0))
        for m in BACKTICK_RE.finditer(seg):
            # `foo()` is already counted; a plain `foo` must still look like code
            # (`len`, `buf` are variables a report names in passing, not claims)
            if not seg[m.end():m.end() + 1] == "(":
                hit(m.group(1), i, seg, base, False)
    return found


def _paths(segs):
    found = {}
    for i, seg in enumerate(segs):
        for m in PATH_RE.finditer(seg):
            p = m.group(1)
            if "://" in seg[max(0, m.start() - 8):m.start() + 3]:
                continue
            rec = found.setdefault(p, {"span": seg, "first": i, "count": 0, "lines": []})
            rec["count"] += 1
            if m.group(2):
                rec["lines"].append((int(m.group(2)), seg))
    return found


def _lines(segs):
    out = []
    for i, seg in enumerate(segs):
        for rx in LINE_RES:
            for m in rx.finditer(seg):
                out.append((int(m.group(1)), seg, i))
    return out


def _tags(segs):
    out = []
    for rx in TAG_RES:                     # pattern order = preference order
        for seg in segs:
            for m in rx.finditer(seg):
                v = m.group(1).rstrip(".")
                if re.search(r"\d", v) and not CWE_RE.fullmatch(v) and v not in [t for t, _ in out]:
                    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", v):     # an IP address, not a version
                        continue
                    out.append((v, seg))
    return out


def _span_for(segs, value):
    value = str(value)
    for seg in segs:
        if value in seg:
            return seg
    return value


def extract_prose(text):
    """Claims from free text, in the validate_claims schema."""
    segs = segments(text)
    header = _header_fields(text)
    claims = []

    # symbols
    syms = _symbols(segs)
    primary_sym = header.get("function")
    if primary_sym and primary_sym not in syms and _is_identifier_like(primary_sym, True):
        syms[primary_sym] = {"span": _span_for(segs, primary_sym), "score": 0, "first": -1}
    if not primary_sym and syms:
        primary_sym = max(syms, key=lambda n: (syms[n]["score"], -syms[n]["first"]))

    # paths
    paths = _paths(segs)
    primary_path = header.get("file")
    if primary_path and primary_path not in paths:
        paths[primary_path] = {"span": _span_for(segs, primary_path), "first": -1, "count": 1, "lines": []}
    if not primary_path and paths:
        near = [p for p in paths if primary_sym and primary_sym in paths[p]["span"]]
        if not near and primary_sym:
            ps = syms[primary_sym]["span"]
            near = [p for p in paths if p in ps]
        pool = near or list(paths)
        primary_path = max(pool, key=lambda p: (paths[p]["count"], -paths[p]["first"]))

    for name in sorted(syms, key=lambda n: syms[n]["first"]):
        claims.append({"type": "symbol", "value": name, "span": syms[name]["span"],
                       "role": "load-bearing" if name == primary_sym else "supporting"})
    for p in sorted(paths, key=lambda q: paths[q]["first"]):
        claims.append({"type": "path", "value": p, "span": paths[p]["span"],
                       "role": "load-bearing" if p == primary_path else "supporting"})

    # line: header field, then "primary_path:N", then "line N" near a path or the primary symbol
    line = None
    if "line" in header:
        field = re.search(ex.FIELD_RE["line"], text).group(0)
        line = (int(header["line"]), _span_for(segs, field), True)
    elif primary_path and paths.get(primary_path, {}).get("lines"):
        n, seg = paths[primary_path]["lines"][0]
        line = (n, seg, True)
    else:
        cands = _lines(segs)
        for n, seg, _ in cands:
            tied = (primary_path and primary_path in seg) or (primary_sym and primary_sym in seg)
            if tied:
                line = (n, seg, True)
                break
        if line is None and cands:
            line = (cands[0][0], cands[0][1], False)
    if line:
        claims.append({"type": "line", "value": str(line[0]), "span": line[1],
                       "role": "load-bearing" if line[2] else "supporting"})

    # version / tag
    tag = header.get("version")
    if tag:
        claims.append({"type": "tag", "value": tag, "span": _span_for(segs, tag), "role": "supporting"})
    else:
        tags = _tags(segs)
        if tags:
            claims.append({"type": "tag", "value": tags[0][0], "span": tags[0][1], "role": "supporting"})

    # CWE
    cwe = header.get("cwe")
    if not cwe:
        m = CWE_RE.search(text)
        cwe = m.group(0) if m else None
    if cwe:
        claims.append({"type": "cwe", "value": cwe, "span": _span_for(segs, cwe), "role": "supporting"})

    # one claim per (type, value); keep the first
    seen, out = set(), []
    for c in claims:
        k = (c["type"], str(c["value"]))
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


class ProseRuleBackend:
    """Drop-in for llm.RuleBackend: same .extract(text) interface, prose-aware."""
    name = "prose-rules"

    def extract(self, text):
        return extract_prose(text)
