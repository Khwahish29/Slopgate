"""Fixture repositories for D1.

A fixture is a directory under corpus/fixtures/<name>/:

    fixture.json   ground truth written by hand: which functions are reachable, dead or
                   callback-only, which one was removed after 1.0, the decoy names that are
                   only mentioned (comment / string literal / docs), and the bugs a report
                   may claim, each anchored to a source line by its text.
    head/          the source tree at the newest version.
    v1_0/          an overlay: the files that differed at the older version.

build_repo() turns that into a real git repository with one commit and one tag per version,
so resolve_tag and git_history have something real to look at. Author, committer and dates
are fixed, so the same fixture always yields the same commit ids.

Nothing here imports the grounding code under test (agent_layer.ground / tools): the
dataset's labels are checked with independent, simpler means.
"""
import json
import os
import re
import shutil
import subprocess

SOURCE_EXT = (".c", ".h")
MARKER = "slopgate_fixture"            # written inside .git so a rebuild only ever deletes our own repos

# Fixture C is written so definitions are easy to find without a parser: a function body opens
# with "{" alone in column 0 and closes with "}" in column 0. The signature is the run of lines
# just above the "{" (one line in the house style; return type, name and wrapped parameters on
# separate lines in the curl style). Prototypes end in ";" and are never bodies.
_DEFINE_RE = re.compile(r"^#\s*define\s+([A-Za-z_]\w*)\(")
_FIRST_CALL_RE = re.compile(r"^[^(]*?\b([A-Za-z_]\w*)\s*\(")
_KEYWORDS = ("if", "for", "while", "switch", "return", "sizeof")


class FixtureError(Exception):
    pass


def read_tree(root):
    """{relative posix path: text} for every file under root."""
    out = {}
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(d, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            with open(p, encoding="utf-8") as fh:
                out[rel] = fh.read()
    return out


def function_index(files):
    """{name: {"file", "start", "end", "kind"}} for every function definition and function-like
    macro in the C files of a tree. start is the line holding the name, end the closing brace (or
    the last continuation line of a macro), both 1-based."""
    idx = {}

    def add(name, rel, start, end, kind):
        if name in idx:
            raise FixtureError("%s defined twice (%s, %s)" % (name, idx[name]["file"], rel))
        idx[name] = {"file": rel, "start": start, "end": end, "kind": kind}

    for rel, text in files.items():
        if not rel.endswith(".c"):
            continue
        lines = text.split("\n")
        for i, line in enumerate(lines):
            m = _DEFINE_RE.match(line)
            if m:
                j = i
                while lines[j].rstrip().endswith("\\"):
                    j += 1
                add(m.group(1), rel, i + 1, j + 1, "macro")
                continue
            if line != "{":
                continue
            k, sig = i - 1, []
            while k >= 0 and lines[k].strip() and not lines[k].startswith("#") \
                    and not lines[k].rstrip().endswith((";", "}", "*/", "{")):
                sig.insert(0, k)
                k -= 1
            m = _FIRST_CALL_RE.match(" ".join(lines[n] for n in sig))
            if not sig or not m or m.group(1) in _KEYWORDS:
                raise FixtureError("%s:%d: '{' in column 0 without a function signature above it" % (rel, i + 1))
            name = m.group(1)
            start = next(n for n in sig if re.search(r"\b%s\s*\(" % name, lines[n])) + 1
            j = i + 1
            while j < len(lines) and lines[j] != "}":
                j += 1
            if j == len(lines):
                raise FixtureError("%s:%d: %s() has no closing brace in column 0" % (rel, i + 1, name))
            add(name, rel, start, j + 1, "function")
    return idx


def line_count(text):
    """Same convention as ground.check_path: number of lines a file iterator yields."""
    return len(text.splitlines())


class Fixture:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        with open(os.path.join(self.path, "fixture.json"), encoding="utf-8") as f:
            self.meta = json.load(f)
        self.name = self.meta["name"]
        head = read_tree(os.path.join(self.path, "head"))
        self.trees = {}                                  # version label -> files
        for v in self.meta["versions"]:
            files = dict(head)
            if v.get("overlay"):
                files.update(read_tree(os.path.join(self.path, v["overlay"])))
            self.trees[v["label"]] = files
        self.head_label = self.meta["versions"][-1]["label"]
        self.index = {label: function_index(files) for label, files in self.trees.items()}
        self.check()

    # ---- convenience --------------------------------------------------------
    def tag(self, label):
        return next(v["tag"] for v in self.meta["versions"] if v["label"] == label)

    def tree(self, label=None):
        return self.trees[label or self.head_label]

    def source_files(self, label=None, ext=(".c",)):
        return sorted(p for p in self.tree(label) if p.endswith(ext))

    def anchor_line(self, label, fn, anchor):
        """1-based line of the first line inside fn() at `label` that contains `anchor`."""
        loc = self.index[label][fn]
        lines = self.trees[label][loc["file"]].split("\n")
        for n in range(loc["start"], loc["end"] + 1):
            if anchor in lines[n - 1]:
                return n
        raise FixtureError("%s@%s: anchor %r not inside %s()" % (self.name, label, anchor, fn))

    def all_text(self):
        """Every file of every version, concatenated: used to prove an invented name is invented."""
        return "\n".join(t for files in self.trees.values() for t in files.values())

    # ---- self-check of the hand-written ground truth ------------------------------
    def check(self):
        head = self.index[self.head_label]
        head_c = "\n".join(self.tree()[p] for p in self.source_files())
        for fn, spec in self.meta["functions"].items():
            if fn not in head:
                raise FixtureError("%s: %s listed in functions but not defined at HEAD" % (self.name, fn))
            calls = len(re.findall(r"\b%s\s*\(" % re.escape(fn), head_c))       # the definition is one of them
            uses = len(re.findall(r"\b%s\b" % re.escape(fn), head_c))
            kind = spec["kind"]
            if kind == "dead" and calls != 1:
                raise FixtureError("%s: %s marked dead but has %d call site(s)" % (self.name, fn, calls - 1))
            if kind == "callback" and not (calls == 1 and uses > 1):
                raise FixtureError("%s: %s marked callback but is not referenced only by value" % (self.name, fn))
            if kind == "macro" and head[fn]["kind"] != "macro":
                raise FixtureError("%s: %s marked macro but is a function" % (self.name, fn))
            if kind in ("reachable", "macro") and calls < 2:
                raise FixtureError("%s: %s marked reachable but is never called" % (self.name, fn))
            for b in spec["bugs"]:
                for label in self.trees:
                    if fn in self.index[label]:
                        self.anchor_line(label, fn, b["anchor"])
        for fn, spec in self.meta.get("removed", {}).items():
            if fn not in self.index[spec["in_label"]]:
                raise FixtureError("%s: removed %s not defined at %s" % (self.name, fn, spec["in_label"]))
            if any(fn in t for p, t in self.tree().items() if p.endswith(SOURCE_EXT)):
                raise FixtureError("%s: removed %s still appears in HEAD sources" % (self.name, fn))
            for b in spec["bugs"]:
                self.anchor_line(spec["in_label"], fn, b["anchor"])
        for name, d in self.meta["decoys"].items():
            for label, idx in self.index.items():
                if name in idx:
                    raise FixtureError("%s: decoy %s is defined at %s" % (self.name, name, label))
            text = self.tree().get(d["file"], "")
            if name not in text:
                raise FixtureError("%s: decoy %s not found in %s" % (self.name, name, d["file"]))
            others = [p for p, t in self.tree().items() if name in t and p != d["file"]]
            if others:
                raise FixtureError("%s: decoy %s also appears in %s" % (self.name, name, others))
            if d["where"] == "docs" and d["file"].endswith(SOURCE_EXT):
                raise FixtureError("%s: docs decoy %s must live in a non-source file" % (self.name, name))


def load_all(root):
    out = []
    for name in sorted(os.listdir(root)):
        if os.path.isfile(os.path.join(root, name, "fixture.json")):
            out.append(Fixture(os.path.join(root, name)))
    if not out:
        raise FixtureError("no fixtures under %s" % root)
    return out


# ---- git materialisation ----------------------------------------------------------

def _git_env(date):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="SlopGate Fixtures", GIT_AUTHOR_EMAIL="fixtures@slopgate.invalid",
               GIT_COMMITTER_NAME="SlopGate Fixtures", GIT_COMMITTER_EMAIL="fixtures@slopgate.invalid",
               GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date,
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, TZ="UTC")
    return env


def _git(repo, env, *args):
    r = subprocess.run(["git", "-C", repo, "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
                        "-c", "core.autocrlf=false", *args],
                       capture_output=True, text=True, env=env, timeout=60)
    if r.returncode != 0:
        raise FixtureError("git %s failed in %s: %s" % (" ".join(args), repo, r.stderr.strip()))
    return r.stdout.strip()


def build_repo(fx, out_root):
    """(Re)build fx as a git repository at out_root/<name>. Returns {"path", "head", "tags"}."""
    dest = os.path.join(out_root, fx.name)
    if os.path.exists(dest):
        if not os.path.isfile(os.path.join(dest, ".git", MARKER)):
            raise FixtureError("%s exists and was not built by this tool; refusing to delete it" % dest)
        shutil.rmtree(dest)
    os.makedirs(dest)
    first = fx.meta["versions"][0]["date"]
    _git(dest, _git_env(first), "init", "-q")
    _git(dest, _git_env(first), "symbolic-ref", "HEAD", "refs/heads/main")
    open(os.path.join(dest, ".git", MARKER), "w").write(fx.name + "\n")
    tags = {}
    for v in fx.meta["versions"]:
        env = _git_env(v["date"])
        for entry in os.listdir(dest):                 # the tree is exactly this version, nothing left over
            if entry != ".git":
                p = os.path.join(dest, entry)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        for rel, text in fx.trees[v["label"]].items():
            p = os.path.join(dest, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        _git(dest, env, "add", "-A")
        _git(dest, env, "commit", "-q", "-m", v["message"])
        _git(dest, env, "tag", v["tag"])
        tags[v["tag"]] = _git(dest, env, "rev-parse", "HEAD")
    return {"path": dest, "head": _git(dest, _git_env(first), "rev-parse", "HEAD"), "tags": tags}
