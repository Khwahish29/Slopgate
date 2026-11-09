"""Tree-sitter grounding (skipped when tree_sitter / tree_sitter_c are not installed)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from slopgate.agent_layer import ground, ts_ground                        # noqa: E402
from slopgate.datasets.fixtures import load_all                           # noqa: E402

CURL_STYLE = """#include "http.h"
#define Curl_safefree(ptr) do { free((ptr)); (ptr) = NULL; } while(0)
static CURLcode http_perhapsrewind(struct Curl_easy *data);

/* Curl_http_done() is called when the transfer is complete. */
CURLcode
Curl_http_done(struct Curl_easy *data, CURLcode status,
               bool premature)
{
  Curl_safefree(data->req.newurl);
  return http_perhapsrewind(data);
}

static CURLcode http_perhapsrewind(struct Curl_easy *data)
{
  infof(data, "http_rewind_body: not needed");
  return CURLE_OK;
}
"""
MAIN = "int main(void)\n{\n  return Curl_http_done(0, 0, 0);\n}\n"


def tree(files):
    d = tempfile.mkdtemp()
    for rel, text in files.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(text)
    return d


def find(repo, sym, mode):
    with mock.patch.dict(os.environ, {"SLOPGATE_PARSER": mode}):
        return ground.find_symbol(repo, sym)


@unittest.skipUnless(ts_ground.available(), "tree-sitter not installed: %s" % ts_ground.IMPORT_ERROR)
class TreeSitter(unittest.TestCase):
    def setUp(self):
        self.repo = tree({"lib/http.c": CURL_STYLE, "src/main.c": MAIN})

    def test_curl_style_definition(self):
        self.assertEqual(find(self.repo, "Curl_http_done", "regex")["status"], "MENTIONED")   # the regex defect
        r = find(self.repo, "Curl_http_done", "treesitter")
        self.assertEqual(r["status"], "DEFINED")
        self.assertEqual(r["definitions"], [{"file": "lib/http.c", "line": 7, "kind": "function"}])
        self.assertEqual(r["callers"], [{"file": os.path.join("src", "main.c"), "line": 3}])
        self.assertTrue(r["checked_by"].startswith("tree-sitter"))

    def test_function_like_macro_is_a_definition(self):
        self.assertEqual(find(self.repo, "Curl_safefree", "regex")["status"], "MENTIONED")
        r = find(self.repo, "Curl_safefree", "treesitter")
        self.assertEqual((r["status"], r["definitions"][0]["kind"]), ("DEFINED", "macro"))

    def test_prototype_is_neither_definition_nor_caller(self):
        rx = find(self.repo, "http_perhapsrewind", "regex")
        self.assertGreater(len(rx["definitions"]), 1)                     # regex: prototype + spurious lines
        r = find(self.repo, "http_perhapsrewind", "treesitter")
        self.assertEqual([d["line"] for d in r["definitions"]], [14])
        self.assertEqual([c["line"] for c in r["callers"]], [11])

    def test_comment_and_string_mentions(self):
        r = find(self.repo, "http_rewind_body", "treesitter")             # only inside a string literal
        self.assertEqual((r["status"], r["code_mentions"]), ("MENTIONED", 0))
        r = find(tree({"a.c": "/* ghost_fn() is gone */\nint x;\n"}), "ghost_fn", "treesitter")
        self.assertEqual((r["status"], r["mention_count"], r["code_mentions"]), ("MENTIONED", 1, 0))

    def test_record_shape_unchanged(self):
        a, b = find(self.repo, "Curl_http_done", "regex"), find(self.repo, "Curl_http_done", "treesitter")
        self.assertEqual(set(a), set(b))

    def test_reachability_through_curl_style_code(self):
        with mock.patch.dict(os.environ, {"SLOPGATE_PARSER": "treesitter"}):
            rec = ground.find_symbol(self.repo, "http_perhapsrewind")
            r = ground.reachable_from_entry(self.repo, "http_perhapsrewind", rec)
        self.assertTrue(r["reachable"], r)
        self.assertEqual(ts_ground.enclosing_function(CURL_STYLE, 10), "Curl_http_done")
        self.assertIsNone(ts_ground.enclosing_function(CURL_STYLE, 2))

    def test_non_c_files_still_use_regex(self):
        repo = tree({"tool.py": "def helper_fn(x):\n    return x\n", "a.c": "int helper_fn_c;\n"})
        r = find(repo, "helper_fn", "treesitter")
        self.assertEqual(r["status"], "DEFINED")
        self.assertIn("regex scan for 1 non-C file", r["checked_by"])

    def test_same_answers_as_regex_on_house_style_fixtures(self):
        """The house-style fixtures are regex-friendly, so the upgrade must not change any status there."""
        for fx in load_all(os.path.join(ROOT, "corpus", "fixtures")):
            if fx.meta.get("style") == "curl":
                continue
            for label, files in fx.trees.items():
                repo = tree(files)
                names = set(fx.index[label]) | set(fx.meta["decoys"])
                for n in sorted(names):
                    self.assertEqual(find(repo, n, "regex")["status"], find(repo, n, "treesitter")["status"],
                                     "%s@%s %s" % (fx.name, label, n))


    def test_ground_truth_on_every_fixture(self):
        """Every function / macro the fixture defines is DEFINED; every decoy is MENTIONED (or ABSENT
        for docs-only decoys, since .md is not a source file). The curl-style fixture is where regex fails."""
        regex_wrong = 0
        for fx in load_all(os.path.join(ROOT, "corpus", "fixtures")):
            for label, files in fx.trees.items():
                repo = tree(files)
                for n in sorted(fx.index[label]):
                    if fx.index[label][n]["kind"] == "macro" and n.isupper():
                        continue                                    # constant-style macros are not claims
                    self.assertEqual(find(repo, n, "treesitter")["status"], "DEFINED", "%s@%s %s" % (fx.name, label, n))
                    regex_wrong += find(repo, n, "regex")["status"] != "DEFINED"
                for n, d in fx.meta["decoys"].items():
                    want = "ABSENT" if d["where"] == "docs" else "MENTIONED"
                    self.assertEqual(find(repo, n, "treesitter")["status"], want, "%s %s" % (fx.name, n))
        self.assertGreater(regex_wrong, 0)                         # the curl-style fixture exposes the regex scan


class ParseErrorFallback(unittest.TestCase):
    @unittest.skipUnless(ts_ground.available(), "tree-sitter not installed")
    def test_ifdef_in_parameter_list_does_not_hide_later_definitions(self):
        # curl lib/socks.c (8.3.0): an #ifdef inside socksstate()'s parameter list breaks the parse,
        # and do_SOCKS5 further down was reported MENTIONED. A real CVE function auto-dismissed.
        src = ("static void socksstate(int a\n#ifdef DEBUG\n, int lineno\n#endif\n)\n{\n  (void)a;\n}\n\n"
               "static int do_SOCKS5(int x,\n                     int y)\n{\n  return x + y;\n}\n"
               "int main(void) { return do_SOCKS5(1, 2); }\n")
        r = find(tree({"socks.c": src}), "do_SOCKS5", "treesitter")
        self.assertEqual(r["status"], "DEFINED")


class WholeIdentifier(unittest.TestCase):
    def test_prefix_of_a_real_name_is_absent_not_mentioned(self):
        # D2 (HackerOne 3418528): the invented Curl_ldap_err2string vs the real Curl_ldap_err2string_a
        src = "const char *Curl_ldap_err2string_a(int e)\n{\n  return 0;\n}\n"
        for mode in ("regex", "treesitter"):
            if mode == "treesitter" and not ts_ground.available():
                continue
            self.assertEqual(find(tree({"os400sys.c": src}), "Curl_ldap_err2string", mode)["status"], "ABSENT")


class Switch(unittest.TestCase):
    def test_modes(self):
        for m in ("regex", "", "nonsense"):
            with mock.patch.dict(os.environ, {"SLOPGATE_PARSER": m}):
                self.assertEqual(ground.parser_mode(), "regex")
        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "SLOPGATE_PARSER"}, clear=True):
            self.assertEqual(ground.parser_mode(), "treesitter" if ts_ground.available() else "regex")   # default: auto
        for m in ("auto", "treesitter"):
            with mock.patch.dict(os.environ, {"SLOPGATE_PARSER": m}):
                self.assertEqual(ground.parser_mode(), "treesitter" if ts_ground.available() else "regex")

    def test_regex_mode_keeps_the_original_record(self):
        repo = tree({"a.c": "int f(void) {\n  return 0;\n}\n"})
        r = find(repo, "f", "regex")
        self.assertEqual(r["checked_by"], ground.REGEX_CHECKED_BY)
        self.assertEqual(r["definitions"], [{"file": "a.c", "line": 1}])


if __name__ == "__main__":
    unittest.main()
