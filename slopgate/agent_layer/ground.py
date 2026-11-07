"""Grounding checks against a real checkout.

The point of this module is the distinction naive grep cannot make:

  MENTIONED  - the token appears somewhere (comment, string, doc, changelog)
  DEFINED    - the token appears as an actual definition site
  REACHABLE  - the definition is called, transitively, from an entry point

A report whose symbol is only MENTIONED is the hard-negative class that makes
a grep-based baseline confidently wrong.
"""
import os
import re

SOURCE_EXT = {".c", ".h", ".py", ".go", ".js", ".ts"}
ENTRY_HINTS = ("main", "int main")


def walk_sources(repo):
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for f in files:
            if os.path.splitext(f)[1] in SOURCE_EXT:
                yield os.path.join(root, f)


# Single pass so that `//` inside a string literal is not mistaken for a
# comment, and `"` inside a comment does not open a string. Alternation order
# is the precedence order of the tokenizer.
_MASK_RE = re.compile(
    r'"(?:[^"\\\n]|\\.)*"'      # double-quoted string
    r"|'(?:[^'\\\n]|\\.)*'"     # char / single-quoted string
    r"|/\*[\s\S]*?\*/"          # C block comment
    r"|//[^\n]*"                # C line comment
    r"|#[^\n]*"                 # preprocessor line / Python comment
)


def _blank(m):
    """Replace a token with spaces, keeping newlines so line numbers survive."""
    return "".join("\n" if c == "\n" else " " for c in m.group(0))


def strip_comments(src):
    """Blank out comments and string literals, preserving offsets and lines."""
    return _MASK_RE.sub(_blank, src)


DEF_PATTERNS = [
    r"^[A-Za-z_][\w \*]*\b{sym}\s*\([^;]*\)\s*\{{",   # C definition
    r"^\s*(static|inline)[\w \*]*\b{sym}\s*\(",        # C static definition
    r"^\s*def\s+{sym}\s*\(",                            # Python
    r"^\s*func\s+{sym}\s*\(",                           # Go
]


def find_symbol(repo, sym):
    """Return a grounding record for one symbol."""
    mentions, defs, callers = [], [], []
    files = list(walk_sources(repo))
    for path in files:
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if sym not in src:
            continue
        rel = os.path.relpath(path, repo)
        code = strip_comments(src)
        code_lines = code.splitlines()
        for i, line in enumerate(src.splitlines(), 1):
            if sym in line:
                in_code = i <= len(code_lines) and sym in code_lines[i - 1]
                mentions.append({"file": rel, "line": i, "in_code": in_code})
        for pat in DEF_PATTERNS:
            for m in re.finditer(pat.format(sym=re.escape(sym)), code, re.M):
                defs.append({"file": rel,
                             "line": code[:m.start()].count("\n") + 1})
        for m in re.finditer(r"\b%s\s*\(" % re.escape(sym), code):
            ln = code[:m.start()].count("\n") + 1
            if not any(d["file"] == rel and abs(d["line"] - ln) < 1 for d in defs):
                callers.append({"file": rel, "line": ln})
    status = "DEFINED" if defs else ("MENTIONED" if mentions else "ABSENT")
    return {
        "symbol": sym,
        "status": status,
        "definitions": defs,
        "mention_count": len(mentions),
        "code_mentions": sum(1 for m in mentions if m["in_code"]),
        "callers": callers,
        "files_searched": len(files),
        "checked_by": "regex definition scan with comment/string stripping",
    }


def reachable_from_entry(repo, sym, record, max_depth=4):
    """Crude transitive reachability from any file containing an entry point."""
    if record["status"] != "DEFINED":
        return {"reachable": None, "reason": "symbol not defined"}
    entry_files = set()
    for path in walk_sources(repo):
        rel = os.path.relpath(path, repo)
        if rel.split(os.sep)[0] in ("tests", "test", "fuzz", "examples"):
            continue  # test harnesses are not production entry points
        src = open(path, encoding="utf-8", errors="replace").read()
        if any(h in src for h in ENTRY_HINTS):
            entry_files.add(rel)
    frontier, seen = {sym}, set()
    for _ in range(max_depth):
        nxt = set()
        for s in frontier:
            if s in seen:
                continue
            seen.add(s)
            r = find_symbol(repo, s)
            for c in r["callers"]:
                if c["file"] in entry_files:
                    return {"reachable": True,
                            "path": "%s <- %s:%d" % (sym, c["file"], c["line"]),
                            "entry_files": sorted(entry_files)}
                fn = _enclosing_function(repo, c["file"], c["line"])
                if fn:
                    nxt.add(fn)
        frontier = nxt
        if not frontier:
            break
    return {"reachable": False,
            "reason": "no call path to an entry point within depth %d" % max_depth,
            "entry_files": sorted(entry_files)}


def _enclosing_function(repo, relpath, line):
    try:
        src = open(os.path.join(repo, relpath), encoding="utf-8",
                   errors="replace").read()
    except OSError:
        return None
    code = strip_comments(src).splitlines()
    for i in range(min(line, len(code)) - 1, -1, -1):
        m = re.match(r"^(?:static\s+|inline\s+)?[\w \*]*?\b([A-Za-z_]\w*)\s*\("
                     r"[^;]*\)\s*\{?\s*$", code[i])
        if m and m.group(1) not in ("if", "for", "while", "switch", "return"):
            return m.group(1)
    return None


def check_path(repo, relpath):
    p = os.path.join(repo, relpath)
    exists = os.path.isfile(p)
    nlines = sum(1 for _ in open(p, encoding="utf-8", errors="replace")) if exists else 0
    return {"path": relpath, "exists": exists, "line_count": nlines}


def check_symbol_location(repo, sym, record, claimed_path):
    """Is the declared function actually defined in the declared file?

    Closes the T5 attack: a forged report can cite a real symbol, a real file
    and an in-range line while lying about which file holds the definition.
    Every check above passes; only the association is false.

    Cost-asymmetric on purpose. A header that merely *declares* the symbol, or
    a comment that names it, is a legitimate thing for a report to cite, so
    anything short of total absence from the claimed file abstains rather than
    convicting. Only "defined here, claimed there, not present there at all"
    is treated as load-bearing.
    """
    if not claimed_path or record["status"] != "DEFINED":
        return None
    homes = sorted({d["file"] for d in record["definitions"]})
    if claimed_path in homes:
        return {"symbol": sym, "claimed": claimed_path, "homes": homes,
                "status": "LOCATED"}
    p = os.path.join(repo, claimed_path)
    if not os.path.isfile(p):
        return None                       # check_path already reports this
    if sym in open(p, encoding="utf-8", errors="replace").read():
        return {"symbol": sym, "claimed": claimed_path, "homes": homes,
                "status": "DECLARED_ONLY"}
    return {"symbol": sym, "claimed": claimed_path, "homes": homes,
            "status": "MISLOCATED"}
