"""D1 generator and fixture repositories."""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from slopgate.agent_layer import ts_ground                                                # noqa: E402
from slopgate.agent_layer.tools import Workspace, find_symbol, resolve_tag, symbol_in_file   # noqa: E402
from slopgate.datasets import d1                                                          # noqa: E402
from slopgate.datasets.fixtures import Fixture, FixtureError, build_repo, load_all       # noqa: E402

FIXTURES = os.path.join(ROOT, "corpus", "fixtures")
AGREED = ("id", "report", "repo", "ref", "gold", "tier")


class D1Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="d1test_")
        cls.out = os.path.join(cls.tmp, "d1")
        cls.repos = os.path.join(cls.tmp, "repos")
        assert d1.main(["--fixtures", FIXTURES, "--repos-out", cls.repos, "--out", cls.out]) == 0
        cls.items = d1.load(os.path.join(cls.out, "d1.jsonl"))
        cls.fx = {f.name: f for f in load_all(FIXTURES)}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_shape_and_counts(self):
        n = len(self.fx)
        self.assertEqual(n, 4)
        self.assertEqual(len(self.items), n * sum(d1.DEFAULT_COUNTS.values()))
        for it in self.items:
            for k in AGREED:
                self.assertIn(k, it)
            self.assertIn(it["gold"], ("HALLUCINATED", "NOT_HALLUCINATED"))
            self.assertIn(it["tier"], ("T1", "T2", "T3", "T4", "T5"))
            self.assertEqual(it["gold"], d1.GOLD[it["tier"]])
            self.assertEqual(open(it["report_path"]).read(), it["report"])
        m = json.load(open(os.path.join(self.out, "manifest.json")))
        inj = d1.DEFAULT_COUNTS["INJ"] // 2
        want = {t: n * d1.DEFAULT_COUNTS[t] + (n * inj if t in ("T1", "T4") else 0) for t in d1.GOLD}
        self.assertEqual(m["by_tier"], want)
        self.assertEqual(set(m["by_style"]), {"fields", "prose", "slop"})
        self.assertEqual(m["with_injection"], n * d1.DEFAULT_COUNTS["INJ"])

    def test_deterministic(self):
        out2, repos2 = os.path.join(self.tmp, "again"), os.path.join(self.tmp, "repos2")
        self.assertEqual(d1.main(["--fixtures", FIXTURES, "--repos-out", repos2, "--out", out2]), 0)
        strip = lambda rows: [{k: v for k, v in r.items() if k not in ("repo", "report_path")} for r in rows]
        self.assertEqual(strip(d1.load(os.path.join(out2, "d1.jsonl"))), strip(self.items))
        a = json.load(open(os.path.join(self.out, "manifest.json")))["repos"]
        b = json.load(open(os.path.join(out2, "manifest.json")))["repos"]
        self.assertEqual({n: r["tags"] for n, r in a.items()}, {n: r["tags"] for n, r in b.items()})
        other = d1.generate(list(self.fx.values()), seed=1)
        self.assertNotEqual([i["report"] for i in other], [i["report"] for i in self.items])

    def test_repos_have_history_and_tags(self):
        for name, fx in self.fx.items():
            ws = Workspace(os.path.join(self.repos, name))
            self.assertEqual(sorted(ws.tags()), sorted(v["tag"] for v in fx.meta["versions"]))
            self.assertEqual(resolve_tag(ws, "v1.0")["tag"], fx.tag("1.0"))

    def test_tools_agree_with_tiers(self):
        """Cross-check the labels with the real tools (the generator itself never imports them).
        The curl-style fixture needs the tree-sitter parser; with regex only it is skipped here
        (test_ts_ground shows why)."""
        mode = "treesitter" if ts_ground.available() else "regex"
        with mock.patch.dict(os.environ, {"SLOPGATE_PARSER": mode}):
            self._tools_agree(mode)

    def _tools_agree(self, mode):
        ws = {}
        for it in self.items:
            if mode == "regex" and self.fx[it["id"].split("-")[1]].meta.get("style") == "curl":
                continue
            w = ws.setdefault(it["repo"], Workspace(it["repo"]))
            c, tier = it["claimed"], it["tier"]
            ref = self.fx[it["id"].split("-")[1]].tag(it["fixture_version"]) if it["fixture_version"] else None
            st = find_symbol(w, c["symbol"], ref)["status"]
            if tier == "T1":
                self.assertEqual(st, "ABSENT", it["id"])
            elif tier == "T2":
                self.assertEqual(st, "ABSENT" if it["subtype"].endswith("docs") else "MENTIONED", it["id"])
            else:
                self.assertEqual(st, "DEFINED", it["id"])
            if tier == "T5":
                self.assertEqual(symbol_in_file(w, c["symbol"], c["path"])["status"], "MISLOCATED", it["id"])
            if tier in ("T3", "T4"):
                self.assertEqual(symbol_in_file(w, c["symbol"], c["path"], ref)["status"], "LOCATED", it["id"])
            if it["subtype"].startswith("removed_after_claimed_version"):
                self.assertEqual(find_symbol(w, c["symbol"])["status"], "ABSENT", it["id"])   # gone at HEAD

    def test_validation_catches_corruption(self):
        by_tier = {}
        for it in self.items:
            by_tier.setdefault(it["tier"], it)
        bad = copy.deepcopy(by_tier["T4"])
        fx = self.fx[bad["id"].split("-")[1]]
        bad["claimed"]["line"] = 1
        with self.assertRaises(d1.LabelError):
            d1.validate_item(fx, bad)
        bad = copy.deepcopy(by_tier["T5"])
        bad["claimed"]["path"] = fx.index[fx.head_label][bad["claimed"]["symbol"]]["file"]   # the true home
        with self.assertRaises(d1.LabelError):
            d1.validate_item(fx, bad)
        bad = copy.deepcopy(by_tier["T1"])
        bad["claimed"]["symbol"] = next(iter(fx.meta["functions"]))
        with self.assertRaises(d1.LabelError):
            d1.validate_item(fx, bad)
        bad = copy.deepcopy(by_tier["T3"])
        bad["gold"] = "HALLUCINATED"
        with self.assertRaises(d1.LabelError):
            d1.validate_item(fx, bad)

    def test_injection_variants_keep_gold(self):
        inj = [i for i in self.items if i["injection"]]
        self.assertEqual({i["tier"] for i in inj}, {"T1", "T4"})
        for i in inj:
            self.assertIn(i["injection"]["text"], i["report"])
            self.assertEqual(i["injection"]["direction"], "to_real" if i["tier"] == "T1" else "to_fake")


class FixtureChecks(unittest.TestCase):
    def copy_fixture(self, name="pktbuf"):
        d = tempfile.mkdtemp()
        shutil.copytree(os.path.join(FIXTURES, name), os.path.join(d, name))
        return os.path.join(d, name)

    def test_wrong_kind_is_rejected(self):
        p = self.copy_fixture()
        meta = json.load(open(os.path.join(p, "fixture.json")))
        meta["functions"]["buf_reserve"]["kind"] = "dead"                  # it is called by buf_append
        json.dump(meta, open(os.path.join(p, "fixture.json"), "w"))
        with self.assertRaises(FixtureError):
            Fixture(p)

    def test_missing_anchor_is_rejected(self):
        p = self.copy_fixture()
        meta = json.load(open(os.path.join(p, "fixture.json")))
        meta["functions"]["tlv_next"]["bugs"][0]["anchor"] = "this text is not in the function"
        json.dump(meta, open(os.path.join(p, "fixture.json"), "w"))
        with self.assertRaises(FixtureError):
            Fixture(p)

    def test_build_refuses_foreign_directory(self):
        out = tempfile.mkdtemp()
        os.makedirs(os.path.join(out, "pktbuf"))
        open(os.path.join(out, "pktbuf", "keep.txt"), "w").write("not ours")
        with self.assertRaises(FixtureError):
            build_repo(Fixture(os.path.join(FIXTURES, "pktbuf")), out)
        self.assertTrue(os.path.exists(os.path.join(out, "pktbuf", "keep.txt")))


if __name__ == "__main__":
    unittest.main()
