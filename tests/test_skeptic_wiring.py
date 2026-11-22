"""Skeptic hook as the agent calls it: ref, re-adjudication, cost reporting, env backend, agent trace."""
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from slopgate.agent_layer import skeptic as sk                          # noqa: E402
from slopgate.agent_layer.ledger import Ledger                          # noqa: E402
from slopgate.agent_layer.llm import LLMBackend, ScriptedClient         # noqa: E402
from slopgate.agent_layer.tools import Workspace, run_tool              # noqa: E402
from test_b1_skeptic import CODE, claims_for, git, repo                 # noqa: E402


def ledger_for(ws, sym, ref=None):
    L = Ledger()
    a = {"name": sym}
    if ref:
        L.add("resolve_tag", {"version": ref}, run_tool(ws, "resolve_tag", {"version": ref}))
        a["ref"] = ref
    L.add("find_symbol", a, run_tool(ws, "find_symbol", a))
    p = dict(path="lib/a.c", **({"ref": ref} if ref else {}))
    L.add("check_path", p, run_tool(ws, "check_path", p))
    return L


class Hook(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(sk._BACKENDS, {"SKEPTIC": None, "XAI": None}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_uses_the_agents_ref(self):
        # the ledger has no resolve_tag row (the agent keeps ref itself); the hook must still see drift
        d = repo({"lib/a.c": "int new_parse(char *p) {\n  return *p;\n}\n"}, history=[{"lib/a.c": CODE}])
        git(d, "tag", "v1.0", "HEAD~1")
        ws = Workspace(d)
        L = Ledger()
        L.add("find_symbol", {"name": "new_parse", "ref": "v1.0"},
              run_tool(ws, "find_symbol", {"name": "new_parse", "ref": "v1.0"}))
        out = sk.skeptic("", L, claims_for("new_parse"), ws, "v1.0")
        self.assertEqual(out["verdict"], "UNVERIFIED")
        self.assertIn("ref_drift", [o["rule"] for o in out["objections"]])

    def test_readjudication_counts(self):
        old = {"lib/a.c": "int ghost_parse(char *p) {\n  return *p;\n}\n"}
        d = repo({"lib/a.c": CODE}, history=[old])
        ws = Workspace(d)
        L = ledger_for(ws, "ghost_parse")
        out = sk.skeptic("", L, claims_for("ghost_parse"), ws, None)
        rules = [o["rule"] for o in out["objections"]]
        self.assertEqual(out["verdict"], "UNVERIFIED")
        self.assertIn("history", rules)
        self.assertIn("readjudicated", rules)                 # git_history REMOVED moves the rule verdict too
        self.assertEqual(out["confidence"], 0.5)

    def test_upheld_fabrication_reports_zero_cost(self):
        d = repo({"lib/a.c": CODE}, history=[])
        ws = Workspace(d)
        out = sk.skeptic("", ledger_for(ws, "ghost_parse"), claims_for("ghost_parse"), ws, None)
        self.assertEqual((out["verdict"], out["model_calls"], out["tokens"]), ("HALLUCINATED", 0, 0))

    def test_model_cost_is_reported(self):
        d = repo({"lib/a.c": CODE})
        ws = Workspace(d)
        client = ScriptedClient(lambda m: json.dumps({"objection": "none", "checks": []}))
        out = sk.skeptic("", ledger_for(ws, "ghost_parse"), claims_for("ghost_parse"), ws, None,
                         backend=LLMBackend(client, "t"))
        self.assertEqual(out["model_calls"], 1)

    def test_model_never_sees_report_text(self):
        d = repo({"lib/a.c": CODE})
        ws = Workspace(d)
        client = ScriptedClient(lambda m: json.dumps({"objection": "", "checks": []}))
        sk.skeptic("SECRET REPORT TEXT", ledger_for(ws, "ghost_parse"), claims_for("ghost_parse"), ws, None,
                   backend=LLMBackend(client, "t"))
        self.assertNotIn("SECRET REPORT TEXT", json.dumps(client.seen))


class EnvBackend(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(sk._BACKENDS, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_key_means_rules_only(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(sk._env_backend("SKEPTIC"))

    def test_cached_capped_and_default_base(self):
        env = {"XAI_API_KEY": "k", "XAI_MODEL": "m", "SLOPGATE_SKEPTIC_MAX_CALLS": "7"}
        with mock.patch.dict(os.environ, env, clear=True):
            b = sk._env_backend("XAI")
            self.assertIs(b, sk._env_backend("XAI"))                 # one client per run: the cap is global
        self.assertEqual(b.client.max_calls, 7)
        self.assertEqual(b.client.base_url, "https://api.x.ai/v1")
        self.assertEqual(b.client.cache_dir, ".slopgate_cache")

    def test_bad_config_is_rules_only_not_a_crash(self):
        with mock.patch.dict(os.environ, {"SKEPTIC_API_KEY": "k"}, clear=True):     # no base url / model
            self.assertIsNone(sk._env_backend("SKEPTIC"))


class AgentTrace(unittest.TestCase):
    """End to end through agent.finalize(): the skeptic's objections and cost reach the result."""

    def test_skeptic_info_in_result(self):
        import test_agent as ta
        with mock.patch.dict(sk._BACKENDS, {"SKEPTIC": None}, clear=True):
            r = ta.run(list(ta.Ablations.HALL), repo=ta.repo_with("int other(void) { return 0; }\n"),
                       use_skeptic=True)[0]
        self.assertEqual(r["skeptic_model_calls"], 0)
        self.assertEqual(r["skeptic_tokens"], 0)
        final = r["trace"][-1]
        self.assertIn("objections", final["skeptic"])

    def test_no_skeptic_no_info(self):
        import test_agent as ta
        r = ta.run(list(ta.Ablations.HALL), repo=ta.repo_with("int other(void) { return 0; }\n"),
                   use_skeptic=False)[0]
        self.assertIsNone(r["trace"][-1]["skeptic"])
        self.assertEqual(r["skeptic_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
