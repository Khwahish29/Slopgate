"""B0 (grep), B2 (single model call, scripted) and the agent ablation registry. Offline."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from slopgate.agent_layer.baselines import REGISTRY, Skipped, build       # noqa: E402
from slopgate.agent_layer.baselines import b2_single                     # noqa: E402
from slopgate.agent_layer.llm import ScriptedClient                      # noqa: E402
from slopgate.agent_layer.tools import Workspace                         # noqa: E402

CODE = "/* chunk_ghost() was planned */\nint chunk_decode(char *p) {\n  return *p;\n}\n"


def repo():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "lib"))
    open(os.path.join(d, "lib", "a.c"), "w").write(CODE)
    return d


def report(sym):
    f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
    f.write("# Overflow\n\nThe overflow is in %s() in lib/a.c around line 2.\n" % sym)
    f.close()
    return f.name


class B0(unittest.TestCase):
    def test_grep_semantics(self):
        d = repo()
        b0 = build("b0")
        self.assertEqual(b0.triage(report("never_there"), Workspace(d), d)["verdict"], "HALLUCINATED")
        self.assertEqual(b0.triage(report("chunk_decode"), Workspace(d), d)["verdict"], "UNVERIFIED")
        # the documented blind spot: a comment-only name counts as present
        self.assertEqual(b0.triage(report("chunk_ghost"), Workspace(d), d)["verdict"], "UNVERIFIED")


class B2(unittest.TestCase):
    def _b2(self, replies):
        s = b2_single.SingleCall.__new__(b2_single.SingleCall)
        s.client = ScriptedClient(replies)
        return s

    def test_skipped_without_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(Skipped):
                build("b2")

    def test_verdict_and_files_in_prompt(self):
        d = repo()
        s = self._b2([json.dumps({"verdict": "HALLUCINATED", "confidence": 0.8, "reason": "no such fn"})])
        r = s.triage(report("never_there"), Workspace(d), d)
        self.assertEqual(r["verdict"], "HALLUCINATED")
        self.assertEqual(r["tool_calls"], 0)
        self.assertIn("lib/a.c", r["files_given"])
        self.assertIn("int chunk_decode", s.client.seen[0][1]["content"])

    def test_bad_output_abstains(self):
        d = repo()
        r = self._b2(["not json"]).triage(report("x_y"), Workspace(d), d)
        self.assertEqual(r["verdict"], "UNVERIFIED")


class Registry(unittest.TestCase):
    def test_all_systems_registered(self):
        for n in ("b0", "b1", "b2", "b2_alt", "b3_rules", "b3_llm", "agent", "agent_no_skeptic",
                  "agent_same_model_skeptic", "agent_no_citation", "agent_no_history"):
            self.assertIn(n, REGISTRY)


if __name__ == "__main__":
    unittest.main()
