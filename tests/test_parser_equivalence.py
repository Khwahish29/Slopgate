"""Parser equivalence: the tree-sitter grounding must agree with the regex scan everywhere the regex
scan is right, and differ only where it is wrong.

The one difference allowed is the one the upgrade exists for (Section 3.3): on curl-style C the regex
scan misses real definitions and reports them MENTIONED. So a difference must go regex MENTIONED ->
tree-sitter DEFINED, never the other way, and tree-sitter must match the fixture's own definition index.
Everything downstream of find_symbol (definition files, the T5 association check, reachability,
enclosing function) must give the same answer whenever both parsers see the same definitions.

Runs on D1 as generated (every claimed symbol in every report) and on every function and decoy of every
fixture version. Skipped when tree-sitter is not installed."""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from slopgate.agent_layer import ground, ts_ground                      # noqa: E402
from slopgate.datasets import d1                                        # noqa: E402
from slopgate.datasets.fixtures import load_all                         # noqa: E402

FIXTURES = os.path.join(ROOT, "corpus", "fixtures")
CURL_STYLE = "curl"                     # fixture meta "style": the regex scan is known to fail here


def run(mode, fn, *args):
    with mock.patch.dict(os.environ, {"SLOPGATE_PARSER": mode}):
        return fn(*args)


def both(fn, *args):
    return run("regex", fn, *args), run("treesitter", fn, *args)


def write_tree(files):
    d = tempfile.mkdtemp(prefix="pareq_")
    for rel, text in files.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    return d


@unittest.skipUnless(ts_ground.available(), "tree-sitter not installed: %s" % ts_ground.IMPORT_ERROR)
class D1Equivalence(unittest.TestCase):
    """Every report in D1, against the fixture repositories D1 is built from."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pareq_d1_")
        out, repos = os.path.join(cls.tmp, "d1"), os.path.join(cls.tmp, "repos")
        assert d1.main(["--fixtures", FIXTURES, "--repos-out", repos, "--out", out]) == 0
        cls.items = d1.load(os.path.join(out, "d1.jsonl"))
        cls.fx = {f.name: f for f in load_all(FIXTURES)}
        cls.records = {}                                  # (repo, sym) -> (regex record, ts record)
        for it in cls.items:
            sym = it["claimed"].get("symbol")
            if sym and (it["repo"], sym) not in cls.records:
                cls.records[(it["repo"], sym)] = both(ground.find_symbol, it["repo"], sym)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fixture(self, it):
        return self.fx[os.path.basename(it["repo"])]

    def test_every_claimed_symbol(self):
        """Same status on house-style fixtures. On curl-style ones a difference is only MENTIONED ->
        DEFINED, and only for a function the fixture really defines at HEAD."""
        checked, diverged = 0, 0
        for it in self.items:
            sym = it["claimed"].get("symbol")
            if not sym:
                continue
            fx = self.fixture(it)
            r, t = self.records[(it["repo"], sym)]
            checked += 1
            if r["status"] == t["status"]:
                continue
            diverged += 1
            msg = "%s %s: regex %s, tree-sitter %s" % (it["id"], sym, r["status"], t["status"])
            self.assertEqual(fx.meta.get("style"), CURL_STYLE, "unexpected difference on a house-style fixture: " + msg)
            self.assertEqual((r["status"], t["status"]), ("MENTIONED", "DEFINED"), msg)
            self.assertIn(sym, fx.index[fx.head_label], "tree-sitter DEFINED a name the fixture does not define: " + msg)
        self.assertGreater(checked, 100)
        self.assertGreater(diverged, 0)                   # the curl-style fixture is in D1 and exposes regex

    def test_definition_files_agree(self):
        """When both parsers find a definition they find it in the same files."""
        for (repo, sym), (r, t) in self.records.items():
            if r["status"] == t["status"] == "DEFINED":
                self.assertEqual({d["file"] for d in r["definitions"]}, {d["file"] for d in t["definitions"]},
                                 "%s %s" % (os.path.basename(repo), sym))

    def test_association_check(self):
        """check_symbol_location (the T5 check) gives the same answer whenever the statuses agree.
        Where tree-sitter recovers a definition the regex scan missed, regex abstains (None)."""
        for it in self.items:
            c = it["claimed"]
            if not c.get("symbol") or not c.get("path"):
                continue
            r, t = self.records[(it["repo"], c["symbol"])]
            lr = run("regex", ground.check_symbol_location, it["repo"], c["symbol"], r, c["path"])
            lt = run("treesitter", ground.check_symbol_location, it["repo"], c["symbol"], t, c["path"])
            if r["status"] == t["status"]:
                self.assertEqual(lr and lr["status"], lt and lt["status"], it["id"])
            else:
                self.assertIsNone(lr, it["id"])
                self.assertIsNotNone(lt, it["id"])

    def test_t5_mislocations_are_caught_only_by_tree_sitter_on_curl_style(self):
        """The case that motivates the upgrade: on curl-style code every T5 report is MISLOCATED under
        tree-sitter, while the regex scan cannot even see the definition."""
        seen = 0
        for it in self.items:
            if it["tier"] != "T5" or self.fixture(it).meta.get("style") != CURL_STYLE:
                continue
            c = it["claimed"]
            r, t = self.records[(it["repo"], c["symbol"])]
            lt = run("treesitter", ground.check_symbol_location, it["repo"], c["symbol"], t, c["path"])
            self.assertEqual(lt and lt["status"], "MISLOCATED", it["id"])
            seen += 1
        self.assertGreater(seen, 0)


@unittest.skipUnless(ts_ground.available(), "tree-sitter not installed: %s" % ts_ground.IMPORT_ERROR)
class FixtureEquivalence(unittest.TestCase):
    """Every function, macro and decoy of every fixture version, not just the ones D1 happens to cite."""

    @classmethod
    def setUpClass(cls):
        cls.trees = []                                    # (fixture, label, repo dir)
        for fx in load_all(FIXTURES):
            for label, files in fx.trees.items():
                cls.trees.append((fx, label, write_tree(files)))

    @classmethod
    def tearDownClass(cls):
        for _, _, d in cls.trees:
            shutil.rmtree(d, ignore_errors=True)

    def test_differences_only_on_curl_style_and_only_toward_defined(self):
        for fx, label, repo in self.trees:
            for n in sorted(set(fx.index[label]) | set(fx.meta["decoys"])):
                r, t = both(ground.find_symbol, repo, n)
                if r["status"] == t["status"]:
                    continue
                msg = "%s@%s %s: regex %s, tree-sitter %s" % (fx.name, label, n, r["status"], t["status"])
                self.assertEqual(fx.meta.get("style"), CURL_STYLE, msg)
                self.assertEqual(t["status"], "DEFINED", msg)
                self.assertIn(n, fx.index[label], msg)

    def test_enclosing_function_on_every_body_line(self):
        """_enclosing_function (used to walk the call graph) names the same function for every line
        strictly inside every function body, and that name is the function's own."""
        for fx, label, repo in self.trees:
            for n, info in fx.index[label].items():
                if info["kind"] != "function":
                    continue
                for line in range(info["start"] + 1, info["end"]):
                    r, t = both(ground._enclosing_function, repo, info["file"], line)
                    self.assertEqual(r, t, "%s@%s %s:%d" % (fx.name, label, info["file"], line))
                    self.assertEqual(t, n, "%s@%s %s:%d" % (fx.name, label, info["file"], line))

    def test_reachability_agrees_when_both_define(self):
        for fx, label, repo in self.trees:
            for n, info in fx.index[label].items():
                if info["kind"] != "function":
                    continue
                r, t = both(ground.find_symbol, repo, n)
                if r["status"] == t["status"] == "DEFINED":
                    a = run("regex", ground.reachable_from_entry, repo, n, r)
                    b = run("treesitter", ground.reachable_from_entry, repo, n, t)
                    self.assertEqual(a["reachable"], b["reachable"], "%s@%s %s" % (fx.name, label, n))


@unittest.skipUnless(ts_ground.available(), "tree-sitter not installed: %s" % ts_ground.IMPORT_ERROR)
class FallbackEquivalence(unittest.TestCase):
    """The regex fallback for files tree-sitter cannot parse must report exactly the regex scan's
    definitions (same files, same lines), tagged as coming from the fallback."""

    # An export macro before the name plus an #ifdef between signature and body: tree-sitter's parse
    # breaks and finds no definition, so ground.py must fall back to the regex scan for this file.
    SRC = ("CURLcode\nCURL_EXPORT do_SOCKS5(int x,\n                      int y)\n#ifdef USE_SOCKS\n#endif\n"
           "{\n  return x + y;\n}\nint main(void) { return do_SOCKS5(1, 2); }\n")

    def test_fallback_definitions_equal_regex_definitions(self):
        self.assertTrue(ts_ground.has_parse_errors(self.SRC))
        self.assertEqual(ts_ground.scan(self.SRC, "lib/socks.c", "do_SOCKS5")[1], [])   # parse alone misses it
        repo = write_tree({"lib/socks.c": self.SRC})
        try:
            r, t = both(ground.find_symbol, repo, "do_SOCKS5")
        finally:
            shutil.rmtree(repo, ignore_errors=True)
        self.assertEqual(r["status"], t["status"])
        self.assertEqual(r["status"], "DEFINED")
        self.assertEqual([(d["file"], d["line"]) for d in r["definitions"]],
                         [(d["file"], d["line"]) for d in t["definitions"]])
        self.assertTrue(all(d.get("via") == "regex-fallback" for d in t["definitions"]))
        self.assertIn("regex fallback in 1 file", t["checked_by"])

    def test_clean_file_never_uses_the_fallback(self):
        repo = write_tree({"lib/a.c": "static int f(int x)\n{\n  return x;\n}\nint main(void) { return f(1); }\n"})
        try:
            r, t = both(ground.find_symbol, repo, "f")
        finally:
            shutil.rmtree(repo, ignore_errors=True)
        self.assertEqual(r["status"], t["status"])
        self.assertFalse(any(d.get("via") == "regex-fallback" for d in t["definitions"]))
        self.assertNotIn("fallback", t["checked_by"])


if __name__ == "__main__":
    unittest.main()
