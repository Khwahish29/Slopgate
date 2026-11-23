"""B2 context building (which files, which lines the model sees) and failure reporting."""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from slopgate.agent_layer.baselines import b2_single                       # noqa: E402
from slopgate.agent_layer.llm import ModelError, RateLimitError, ScriptedClient  # noqa: E402
from slopgate.agent_layer.tools import Workspace                           # noqa: E402


def tree(files):
    d = tempfile.mkdtemp()
    for rel, body in files.items():
        os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
        open(os.path.join(d, rel), "w").write(body)
    return d


def big_file(defn_at=400, n=900):
    lines = ["/* filler line %d */" % i for i in range(1, n + 1)]
    lines[defn_at - 1] = "int deep_function(char *p) {"
    lines[defn_at] = "  return p[0];"
    lines[defn_at + 1] = "}"
    return "\n".join(lines) + "\n"


class ResolveFile(unittest.TestCase):
    def test_exact_path(self):
        d = tree({"lib/a.c": "x"})
        self.assertEqual(b2_single.resolve_file(d, "lib/a.c"), os.path.join("lib", "a.c"))

    def test_bare_name_found_when_unique(self):
        d = tree({"lib/cookie.c": "x", "src/main.c": "y"})
        self.assertEqual(b2_single.resolve_file(d, "cookie.c"), os.path.join("lib", "cookie.c"))

    def test_bare_name_ambiguous_or_missing_is_none(self):
        d = tree({"lib/util.c": "x", "src/util.c": "y"})
        self.assertIsNone(b2_single.resolve_file(d, "util.c"))
        self.assertIsNone(b2_single.resolve_file(d, "nothing.c"))

    def test_cannot_escape_the_repository(self):
        d = tree({"lib/a.c": "x"})
        self.assertIsNone(b2_single.resolve_file(d, "../../etc/passwd.c"))
        self.assertIsNone(b2_single.resolve_file(d, "/etc/passwd"))

    def test_git_directory_is_not_searched(self):
        d = tree({".git/objects/x.c": "x"})
        self.assertIsNone(b2_single.resolve_file(d, "x.c"))


class NamedFiles(unittest.TestCase):
    def test_links_are_not_files(self):
        d = tree({"lib/a.c": "int f(void) { return 0; }\n"})
        text = ("See https://github.com/owner/repo/blob/main/lib/a.c and "
                "https://cwe.mitre.org/data/definitions/787.html and lib/a.c")
        out = b2_single.named_files(Workspace(d), text)
        self.assertEqual([p for p, _ in out], [os.path.join("lib", "a.c")])

    def test_bare_filename_is_shown_not_reported_missing(self):
        d = tree({"lib/cookie.c": "int cookie_add(void) { return 0; }\n"})
        out = b2_single.named_files(Workspace(d), "The bug is in cookie.c, in cookie_add().")
        self.assertEqual(out[0][0], os.path.join("lib", "cookie.c"))
        self.assertIn("cookie_add", out[0][1])

    def test_missing_file_is_marked_missing(self):
        d = tree({"lib/a.c": "x\n"})
        self.assertEqual(b2_single.named_files(Workspace(d), "see lib/ghost.c"), [("lib/ghost.c", None)])


class RenderFile(unittest.TestCase):
    def test_small_file_is_shown_whole(self):
        lines = ["int a;", "int b;"]
        out = b2_single.render_file(lines, "", "x.c")
        self.assertIn("   1  int a;", out)
        self.assertNotIn("omitted", out)

    def test_long_file_keeps_the_cited_function(self):
        src = big_file(defn_at=400).splitlines()
        text = "`deep_function()` in lib/big.c overflows"
        out = b2_single.render_file(src, text, "lib/big.c")
        self.assertIn("int deep_function", out)             # the old head-only cut would lose this
        self.assertIn("omitted", out)
        self.assertLessEqual(len(out), b2_single.MAX_FILE_CHARS + 600)    # budget plus omission markers
        self.assertIn("   1  /* filler line 1 */", out)      # head is kept

    def test_cited_line_window(self):
        src = big_file(defn_at=700).splitlines()
        out = b2_single.render_file(src, "overflow at lib/big.c:700", "lib/big.c")
        self.assertIn("int deep_function", out)

    def test_nothing_named_still_returns_the_head(self):
        out = b2_single.render_file(big_file().splitlines(), "no hints here", "lib/big.c")
        self.assertIn("filler line 1 ", out)
        self.assertIn("lines omitted", out)

    def test_cited_names_and_lines(self):
        self.assertEqual(b2_single.cited_names("`foo_bar()` calls baz_qux() and `memset`"), ["foo_bar", "memset", "baz_qux"])
        self.assertEqual(b2_single.cited_lines("lib/a.c:214 and line 9", "lib/a.c"), [214, 9])


class Failures(unittest.TestCase):
    def _b2(self, client):
        s = b2_single.SingleCall.__new__(b2_single.SingleCall)
        s.client = client
        return s

    def _report(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        f.write("# Overflow\n\n`deep_function()` in lib/big.c overflows.\n")
        f.close()
        return f.name

    def test_deep_function_reaches_the_model(self):
        d = tree({"lib/big.c": big_file()})
        c = ScriptedClient([json.dumps({"verdict": "UNVERIFIED", "confidence": 0.7, "reason": "defined"})])
        r = self._b2(c).triage(self._report(), Workspace(d), d)
        self.assertIn("int deep_function", c.seen[0][1]["content"])
        self.assertEqual(r["verdict"], "UNVERIFIED")
        self.assertIsNone(r["model_error"])

    def test_rate_limit_abstains_and_says_why(self):
        d = tree({"lib/big.c": big_file()})

        class Limited:
            calls = tokens = retries = 0
            rate_limited = 3

            def chat(self, messages, ref=""):
                raise RateLimitError("HTTPError 429 (Retry-After: 4)", 4.0)

        r = self._b2(Limited()).triage(self._report(), Workspace(d), d)
        self.assertEqual(r["verdict"], "UNVERIFIED")        # never a dismissal on a failed call
        self.assertIn("RateLimitError", r["model_error"])
        self.assertIn("model error", r["rationale"][0]["text"])

    def test_bad_json_abstains_with_error_recorded(self):
        d = tree({"lib/big.c": big_file()})
        r = self._b2(ScriptedClient(["not json"])).triage(self._report(), Workspace(d), d)
        self.assertEqual(r["verdict"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
