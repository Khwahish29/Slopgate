"""Typed, read-only tools. The model picks arguments; it never writes results.

Every tool takes an explicit ref (or none for the working tree), enforces a
timeout on anything that shells out, and returns compact JSON with a `status`.
A tool failure is reported as INCONCLUSIVE and is never evidence of absence.

The grounding logic itself is the unchanged baseline in ground.py.
"""
import difflib
import os
import re
import shutil
import subprocess
import tempfile

from . import ground

GIT_TIMEOUT = 20
_REF_RE = re.compile(r"^[A-Za-z0-9][\w./\-]*$")      # no leading '-': blocks git option injection
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{1,80}$")


class ToolError(Exception):
    pass


class Workspace:
    """A repository plus cached, read-only checkouts of the refs asked about."""

    def __init__(self, repo):
        self.repo = os.path.abspath(repo)
        # .git is a directory in a clone but a file in a `git worktree` (D2 pins use worktrees)
        self.is_git = os.path.exists(os.path.join(self.repo, ".git"))
        self._tmp = tempfile.mkdtemp(prefix="slopgate_ws_")
        self._checkouts = {}
        self._sym = {}                 # repository memory: (checkout, name) -> grounding record
        self.cache_hits = 0

    def close(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], capture_output=True,
                              text=True, timeout=GIT_TIMEOUT)

    def tags(self):
        if not self.is_git:
            return None
        r = self.git("tag", "--list")
        return [t.strip() for t in r.stdout.splitlines() if t.strip()] if r.returncode == 0 else None

    def find(self, root, name):
        """ground.find_symbol with a per-checkout cache. Holds facts about code only, never
        verdicts, so one report cannot influence the next."""
        key = (root, name)
        if key in self._sym:
            self.cache_hits += 1
        else:
            self._sym[key] = ground.find_symbol(root, name)
        return self._sym[key]

    def checkout(self, ref):
        """(path, ref_used). Unknown refs fall back to the working tree, and say so."""
        if not ref or not self.is_git:
            return self.repo, "WORKTREE"
        if not _REF_RE.match(ref):
            raise ToolError("invalid ref %r" % ref)
        r = self.git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
        if r.returncode != 0:
            return self.repo, "WORKTREE"
        commit = r.stdout.strip()
        if commit not in self._checkouts:
            dest = os.path.join(self._tmp, commit[:12])
            os.makedirs(dest)
            a = subprocess.Popen(["git", "-C", self.repo, "archive", commit],
                                 stdout=subprocess.PIPE)
            subprocess.run(["tar", "-x", "-C", dest], stdin=a.stdout, check=True,
                           timeout=GIT_TIMEOUT * 3)
            a.stdout.close()
            a.wait(timeout=GIT_TIMEOUT)
            self._checkouts[commit] = dest
        return self._checkouts[commit], commit[:10]


def _safe_path(p):
    if not p or os.path.isabs(p) or ".." in p.replace("\\", "/").split("/"):
        raise ToolError("path must be relative and stay inside the repository")
    return p


def _name(n):
    if not isinstance(n, str) or not _NAME_RE.match(n):
        raise ToolError("symbol name must be an identifier")
    return n


def _loc(rec):
    d = rec["definitions"][0] if rec.get("definitions") else None
    return "%s:%d" % (d["file"], d["line"]) if d else ""


# ---- tools ---------------------------------------------------------------

def find_symbol(ws, name, ref=None):
    path, used = ws.checkout(ref)
    rec = ws.find(path, _name(name))
    return {"status": rec["status"], "ref_used": used, "record": rec, "location": _loc(rec)}


def symbol_in_file(ws, name, path, ref=None):
    root, used = ws.checkout(ref)
    _safe_path(path)
    rec = ws.find(root, _name(name))
    loc = ground.check_symbol_location(root, name, rec, path)
    if loc is None:
        status = "NOT_DEFINED" if rec["status"] != "DEFINED" else "NO_SUCH_FILE"
        return {"status": status, "ref_used": used, "record": rec, "location": ""}
    return {"status": loc["status"], "ref_used": used, "record": rec, "loc": loc,
            "location": path}


def check_path(ws, path, ref=None):
    root, used = ws.checkout(ref)
    r = ground.check_path(root, _safe_path(path))
    return {"status": "EXISTS" if r["exists"] else "ABSENT", "ref_used": used,
            "path": path, "exists": r["exists"], "line_count": r["line_count"],
            "location": path if r["exists"] else ""}


def check_line_range(ws, path, line, ref=None):
    if not isinstance(line, int) or line < 1:
        raise ToolError("line must be a positive integer")
    r = check_path(ws, path, ref)
    ok = bool(r["exists"] and line <= r["line_count"])
    return {"status": "IN_RANGE" if ok else ("OUT_OF_RANGE" if r["exists"] else "ABSENT"),
            "ref_used": r["ref_used"], "path": path, "claimed": line,
            "file_lines": r["line_count"], "in_range": ok, "location": "%s:%d" % (path, line)}


def _nums(s):
    return re.findall(r"\d+", s)


def resolve_tag(ws, version):
    tags = ws.tags()
    if tags is None:
        return {"status": "UNKNOWN", "version": version, "note": "not a git checkout"}
    if re.fullmatch(r"[0-9a-f]{7,40}", version):
        r = ws.git("rev-parse", "--verify", "--quiet", version + "^{commit}")
        if r.returncode == 0:
            return {"status": "FOUND", "version": version, "tag": r.stdout.strip()[:12],
                    "known_tags": tags[:10]}
    want = _nums(version)
    hit = next((t for t in tags if t == version or (want and _nums(t) == want)), None)
    if hit:
        return {"status": "FOUND", "version": version, "tag": hit, "known_tags": tags[:10]}
    near = difflib.get_close_matches(version, tags, n=3, cutoff=0.4)
    return {"status": "NOT_FOUND", "version": version, "nearest": near, "known_tags": tags[:10]}


def git_history(ws, name):
    """Separate 'removed' from 'never existed' using git log -S."""
    if not ws.is_git:
        return {"status": "UNKNOWN", "note": "not a git checkout", "commits": []}
    _name(name)
    r = ws.git("log", "-S" + name, "--format=%H%x09%ad%x09%s", "--date=short", "-n", "20")
    if r.returncode != 0:
        return {"status": "UNKNOWN", "note": r.stderr.strip()[:120], "commits": []}
    commits = []
    word = re.compile(r"\b%s\b" % re.escape(name))
    for line in r.stdout.splitlines():
        sha, date, subj = (line.split("\t", 2) + ["", ""])[:3]
        d = ws.git("show", "--format=", "-U0", "--no-color", sha).stdout
        plus = sum(1 for x in d.splitlines() if x.startswith("+") and not x.startswith("+++") and word.search(x))
        minus = sum(1 for x in d.splitlines() if x.startswith("-") and not x.startswith("---") and word.search(x))
        kind = "added" if plus > minus else "removed" if minus > plus else "changed"
        commits.append({"commit": sha[:10], "date": date, "subject": subj[:80], "kind": kind})
    if not commits:
        status = "NEVER_IN_HISTORY"
    elif commits[0]["kind"] == "removed":          # git log lists newest first
        status = "REMOVED"
    else:
        status = "PRESENT_IN_HISTORY"
    return {"status": status, "commits": commits,
            "location": commits[0]["commit"] if commits else ""}


def check_reachability(ws, name, ref=None):
    root, used = ws.checkout(ref)
    rec = ws.find(root, _name(name))
    r = ground.reachable_from_entry(root, name, rec)
    if r["reachable"] is None:
        return {"status": "N/A", "ref_used": used, "reachable": None, "reason": r["reason"]}
    if r["reachable"]:
        return {"status": "REACHABLE", "ref_used": used, "reachable": True, "path": r["path"],
                "location": r["path"]}
    # Not found by direct calls. If the name is also used as a value (callback,
    # function pointer, macro argument) the static graph is incomplete, so say
    # UNCERTAIN rather than UNREACHABLE.
    indirect = 0
    for p in ground.walk_sources(root):
        code = ground.strip_comments(open(p, encoding="utf-8", errors="replace").read())
        indirect += len(re.findall(r"\b%s\b" % re.escape(name), code)) \
            - len(re.findall(r"\b%s\s*\(" % re.escape(name), code))
    if indirect > 0:
        return {"status": "UNCERTAIN", "ref_used": used, "reachable": None,
                "reason": "%d indirect reference(s) (callback or function pointer); "
                          "static call graph incomplete" % indirect}
    return {"status": "UNREACHABLE", "ref_used": used, "reachable": False, "reason": r["reason"]}


# ---- registry: JSON schemas the planner sees -------------------------------

def _schema(props, required):
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


S, I = {"type": "string"}, {"type": "integer"}
TOOLS = {
    "find_symbol": (find_symbol, _schema({"name": S, "ref": S}, ["name"]),
                    "ABSENT / MENTIONED / DEFINED; comments and strings blanked"),
    "symbol_in_file": (symbol_in_file, _schema({"name": S, "path": S, "ref": S}, ["name", "path"]),
                       "is the symbol defined in this file (LOCATED / DECLARED_ONLY / MISLOCATED)"),
    "check_path": (check_path, _schema({"path": S, "ref": S}, ["path"]), "file exists, real length"),
    "check_line_range": (check_line_range, _schema({"path": S, "line": I, "ref": S}, ["path", "line"]),
                         "line number inside the file"),
    "resolve_tag": (resolve_tag, _schema({"version": S}, ["version"]),
                    "version string to tag or commit, else NOT_FOUND with nearest tags"),
    "git_history": (git_history, _schema({"name": S}, ["name"]),
                    "commits that added or removed the symbol (git log -S)"),
    "check_reachability": (check_reachability, _schema({"name": S, "ref": S}, ["name"]),
                           "path from a non-test entry point; indirect calls are UNCERTAIN"),
}


def validate_call(name, args):
    if name not in TOOLS:
        raise ToolError("unknown tool %r" % name)
    sch = TOOLS[name][1]
    if not isinstance(args, dict):
        raise ToolError("args must be an object")
    for k in sch["required"]:
        if k not in args:
            raise ToolError("missing argument %r" % k)
    for k, v in args.items():
        if k not in sch["properties"]:
            raise ToolError("unexpected argument %r" % k)
        if sch["properties"][k]["type"] == "integer" and not isinstance(v, int):
            raise ToolError("%r must be an integer" % k)
        if sch["properties"][k]["type"] == "string" and not isinstance(v, str):
            raise ToolError("%r must be a string" % k)


def run_tool(ws, name, args):
    """Run one tool. Errors become INCONCLUSIVE observations, never contradictions."""
    try:
        validate_call(name, args)
        return TOOLS[name][0](ws, **args)
    except ToolError as e:
        return {"status": "INCONCLUSIVE", "error": str(e)}
    except subprocess.TimeoutExpired:
        return {"status": "INCONCLUSIVE", "error": "timeout"}
    except Exception as e:  # noqa: BLE001
        return {"status": "INCONCLUSIVE", "error": "%s: %s" % (type(e).__name__, e)}
