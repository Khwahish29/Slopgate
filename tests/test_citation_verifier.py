"""Citation verifier / verdict stage: deterministic, no network."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from slopgate.agent_layer import agent as ag                                 # noqa: E402
from slopgate.agent_layer import citation_verifier as cv                     # noqa: E402
from slopgate.agent_layer.ledger import Ledger                               # noqa: E402
from slopgate.agent_layer.tools import Workspace, run_tool                   # noqa: E402
import test_agent as T                                                       # noqa: E402

SPAN = T.SPAN


def c(cid, t, v, role, span=SPAN):
    return {"id": cid, "type": t, "value": v, "span": span, "role": role}


def ledger_of(repo, calls):
    ws, L = Workspace(repo), Ledger()
    for tool, args in calls:
        L.add(tool, args, run_tool(ws, tool, args), by="agent")
    return L


MISSING = "int other(void) { return 0; }\n"
LB = c("C1", "symbol", "chunk_decode", "load-bearing")
PATH = c("C2", "path", "lib/a.c", "supporting")


class Stance(unittest.TestCase):
    def test_stance(self):
        s = cv.stance
        self.assertEqual(s("chunk_decode was not found in the tree [E1]."), "negative")
        self.assertEqual(s("chunk_decode is not defined [E1]."), "negative")
        self.assertEqual(s("Missing [E1]."), "negative")
        self.assertEqual(s("It is defined [E1]."), "positive")
        self.assertEqual(s("chunk_decode is defined elsewhere, not in lib/b.c [E2]."), "mixed")
        self.assertEqual(s("The lookup timed out, so the symbol is unchecked [E1]."), "hedge")
        self.assertEqual(s("History only [E1]."), "neutral")


class Sentences(unittest.TestCase):
    def setUp(self):
        self.repo = T.repo_with(extra=["b.c"])
        self.L = ledger_of(self.repo, [("find_symbol", {"name": "chunk_decode"}),     # E1 DEFINED in lib/a.c
                                       ("check_path", {"path": "lib/zzz.c"})])        # E2 ABSENT
        self.claims = [LB, PATH, c("C3", "path", "lib/zzz.c", "supporting")]

    def keep(self, text):
        return [(s["keep"], s["reason"]) for s in cv.check_rationale(text, self.L, self.claims)]

    def test_supported_sentences_survive(self):
        self.assertTrue(self.keep("chunk_decode is defined in lib/a.c [E1].")[0][0])
        self.assertTrue(self.keep("lib/zzz.c does not exist [E2].")[0][0])
        self.assertTrue(self.keep("find_symbol returned DEFINED (GROUND) [E1].")[0][0])

    def test_reachability_path_counts_as_checked(self):
        repo = T.repo_with()
        os.makedirs(os.path.join(repo, "src"))
        open(os.path.join(repo, "src", "main.c"), "w").write("int main(void) { return chunk_decode(0); }\n")
        L = ledger_of(repo, [("check_reachability", {"name": "chunk_decode"})])
        self.assertEqual(L.rows[0]["status"], "REACHABLE")
        out = cv.check_rationale("chunk_decode is reachable from src/main.c [E1].", L, [LB])
        self.assertTrue(out[0]["keep"], out[0]["reason"])

    def test_unchecked_entity_dropped(self):
        keep, why = self.keep("chunk_decode is defined [E1] and lib/evil.c is absent [E1].")[0]
        self.assertFalse(keep)
        self.assertIn("lib/evil.c", why)

    def test_misattributed_citation_dropped(self):
        keep, why = self.keep("lib/zzz.c is missing [E1].")[0]
        self.assertFalse(keep)
        self.assertIn("lib/zzz.c", why)

    def test_polarity_conflict_dropped(self):
        keep, why = self.keep("chunk_decode is not defined anywhere [E1].")[0]
        self.assertFalse(keep)
        self.assertIn("found it", why)
        self.assertFalse(self.keep("lib/zzz.c exists [E2].")[0][0])

    def test_misquoted_status_dropped(self):
        keep, why = self.keep("find_symbol returned ABSENT [E1].")[0]
        self.assertFalse(keep)
        self.assertIn("ABSENT", why)

    def test_uncited_and_overflow_sentences_dropped(self):
        out = self.keep("Defined [E1]. No citation here. A [E1]. B [E1]. C [E1]. D [E1].")
        self.assertEqual([k for k, _ in out], [True, False, True, True, True, False])
        self.assertIn("limit", out[-1][1])

    def test_inconclusive_only_definite_claim_dropped_hedge_kept(self):
        L = Ledger()
        L.add("find_symbol", {"name": "chunk_decode"}, {"status": "INCONCLUSIVE", "error": "timeout"})
        self.assertFalse(cv.check_rationale("chunk_decode is missing [E1].", L, [LB])[0]["keep"])
        self.assertTrue(cv.check_rationale("The lookup for chunk_decode timed out [E1].", L, [LB])[0]["keep"])


class Verdicts(unittest.TestCase):
    def hall_ledger(self):
        return ledger_of(T.repo_with(MISSING), [("find_symbol", {"name": "chunk_decode"})])

    def test_supported_hallucinated_is_kept(self):
        v, text, ev = cv.verify("HALLUCINATED", "chunk_decode does not exist [E1].",
                                               self.hall_ledger(), [LB], [])
        self.assertEqual(v, "HALLUCINATED")
        self.assertEqual(text, "chunk_decode does not exist [E1].")
        self.assertTrue(any("confirmed by the rule adjudicator" in e for e in ev))

    def test_fake_id_poisons_verdict(self):
        v, _, ev = cv.verify("HALLUCINATED", "chunk_decode does not exist [E1]. See also [E7].",
                                            self.hall_ledger(), [LB], [])
        self.assertEqual(v, "UNVERIFIED")
        self.assertIn("nonexistent", " ".join(ev))

    def test_hallucinated_needs_load_bearing_contradiction(self):
        repo = T.repo_with()
        L = ledger_of(repo, [("find_symbol", {"name": "ghost_fn"}), ("find_symbol", {"name": "chunk_decode"})])
        claims = [LB, c("C2", "symbol", "ghost_fn", "supporting")]
        v, _, ev = cv.verify("HALLUCINATED", "ghost_fn does not exist [E1].", L, claims, [])
        self.assertEqual(v, "UNVERIFIED")
        self.assertIn("load-bearing CONTRADICTION", " ".join(ev))

    def test_polarity_drop_downgrades(self):
        L = ledger_of(T.repo_with(), [("find_symbol", {"name": "chunk_decode"})])        # DEFINED
        v, text, ev = cv.verify("HALLUCINATED", "Missing [E1].", L, [LB], [])
        self.assertEqual(v, "UNVERIFIED")
        self.assertIn("no cited sentences survived", " ".join(ev))
        self.assertIn("[E1]", text)                                       # summary rationale, still cited

    def test_reproducible_never_survives(self):
        L = ledger_of(T.repo_with(), [("find_symbol", {"name": "chunk_decode"})])
        v, _, _ = cv.verify("REPRODUCIBLE", "chunk_decode is defined [E1].", L, [LB], [])
        self.assertEqual(v, "UNVERIFIED")

    def test_never_upgrades(self):
        v, _, _ = cv.verify("UNVERIFIED", "chunk_decode does not exist [E1].",
                                           self.hall_ledger(), [LB], [])
        self.assertEqual(v, "UNVERIFIED")

    def test_unresolved_ref_pair_is_not_a_contradiction(self):
        # same shape as test_agent.test_pair_at_unresolved_ref: MISLOCATED after a tag that did not resolve
        L = Ledger()
        L.add("resolve_tag", {"version": "v9.9"}, {"status": "NOT_FOUND", "version": "v9.9", "known_tags": []})
        L.add("symbol_in_file", {"name": "chunk_decode", "path": "lib/b.c"}, {"status": "MISLOCATED", "location": "lib/b.c"})
        claims = [c("C1", "symbol", "chunk_decode", "load-bearing"), c("C2", "path", "lib/b.c", "supporting"),
                  c("C3", "tag", "v9.9", "supporting", "Version: v9.9")]
        meta = cv.rebuild_meta(L, claims)
        self.assertEqual([meta["E1"]["cls"], meta["E2"]["cls"]], ["CONTRADICTION", "INCONCLUSIVE"])
        v, _, _ = cv.verify("HALLUCINATED", "chunk_decode is not in lib/b.c [E2].", L, claims, [])
        self.assertEqual(v, "UNVERIFIED")

    def test_random_rationales_never_beat_the_rules(self):
        """Property: whatever the model writes, HALLUCINATED survives only when proposed AND the rule
        adjudicator agrees on the load-bearing ledger."""
        rng = random.Random(7)
        words = ["chunk_decode", "lib/a.c", "lib/b.c", "is", "not", "defined", "missing", "exists", "found",
                 "ABSENT", "DEFINED", "MISLOCATED", "in", "the", "tree", "elsewhere", "timed out"]
        setups = [(T.repo_with(MISSING), [("find_symbol", {"name": "chunk_decode"})]),
                  (T.repo_with(extra=["b.c"]), [("find_symbol", {"name": "chunk_decode"}),
                                                ("symbol_in_file", {"name": "chunk_decode", "path": "lib/b.c"})]),
                  (T.repo_with(), [("find_symbol", {"name": "chunk_decode"}), ("check_path", {"path": "lib/a.c"})])]
        claims = [LB, c("C2", "path", "lib/b.c", "supporting")]
        for repo, calls in setups:
            L = ledger_of(repo, calls)
            meta = cv.rebuild_meta(L, claims)
            lb, view = ag.guard_view(L, meta, claims)
            det = cv.verifier.deterministic_verdict(view, lb, [])["verdict"]
            for _ in range(150):
                sents = [" ".join(rng.choice(words) for _ in range(rng.randint(2, 7)))
                         + "".join(" [E%d]" % rng.randint(1, 3) for _ in range(rng.randint(0, 2))) + "."
                         for _ in range(rng.randint(1, 4))]
                p = rng.choice(ag.VERDICTS)
                v, _, _ = cv.verify(p, " ".join(sents), L, claims, [])
                self.assertIn(v, ag.VERDICTS)
                self.assertNotEqual(v, "REPRODUCIBLE")
                if v == "HALLUCINATED":
                    self.assertEqual((p, det), ("HALLUCINATED", "HALLUCINATED"))


class AgainstTheAgent(unittest.TestCase):
    """rebuild_meta must agree with the classes the agent loop computed while it ran."""

    def check(self, replies, **kw):
        r, _ = T.run(replies, **kw)
        L = Ledger()
        L.rows = r["ledger"]
        meta = cv.rebuild_meta(L, r["claims"])
        self.assertEqual([meta[x["id"]]["cls"] for x in r["ledger"]], T.classes(r))
        self.assertIn("citation_verifier hook used", r["trace"][-1]["finalize_events"])
        return r

    def test_classes_match_the_loop(self):
        A = T.Association
        sym = T.claim("symbol", "chunk_decode", "load-bearing", A.WRONG)
        path = T.claim("path", "lib/b.c", "supporting", A.WRONG)
        tag = T.claim("tag", "v1.0", "supporting", "Version: v1.0")
        r = self.check([T.claims_reply(sym, path, tag),
                        T.call("symbol_in_file", "C1", name="chunk_decode", path="lib/b.c"),
                        T.call("resolve_tag", "C3", version="v1.0"),
                        T.call("symbol_in_file", "C1", name="chunk_decode", path="lib/b.c"),
                        T.verdict("HALLUCINATED", "chunk_decode is not in lib/b.c [E3].")],
                       text=A.WRONG_REPORT + "Version: v1.0\n", repo=T.repo_with(extra=["b.c"]))
        self.assertEqual(r["verdict"], "HALLUCINATED")
        stray = T.claim("path", "lib/b.c", "supporting", "See also lib/b.c for the build.")
        self.check([T.claims_reply(T.LB_SYM, T.SUP_PATH, stray),
                    T.call("symbol_in_file", "C1", name="chunk_decode", path="lib/b.c"),
                    T.call("symbol_in_file", "C1", name="chunk_decode", path="lib/a.c"),
                    T.call("check_path", "C2", path="lib/a.c"), T.call("check_path", "C3", path="lib/b.c"),
                    T.verdict("UNVERIFIED", "chunk_decode is defined in lib/a.c [E2].")],
                   text=T.REPORT + "See also lib/b.c for the build.\n", repo=T.repo_with(extra=["b.c"]))

    def test_misattributed_rationale_is_trimmed_in_the_loop(self):
        r = self.check([T.claims_reply(T.LB_SYM), T.call("find_symbol", "C1", name="chunk_decode"),
                        T.verdict("HALLUCINATED", "chunk_decode does not exist [E1]. lib/evil.c is absent [E1].")],
                       repo=T.repo_with(MISSING))
        self.assertEqual(r["verdict"], "HALLUCINATED")
        self.assertEqual([s["text"] for s in r["rationale"]], ["chunk_decode does not exist [E1]."])

    def test_polarity_drop_downgrades_in_the_loop(self):
        r = self.check([T.claims_reply(T.LB_SYM), T.call("find_symbol", "C1", name="chunk_decode"),
                        T.verdict("UNVERIFIED", "chunk_decode is not defined anywhere [E1].")])     # it is defined
        self.assertEqual(r["verdict"], "UNVERIFIED")
        self.assertNotIn("not defined anywhere", " ".join(s["text"] for s in r["rationale"]))

    def test_fake_id_defers_to_the_agents_own_check(self):
        L = ledger_of(T.repo_with(MISSING), [("find_symbol", {"name": "chunk_decode"})])
        self.assertEqual(cv.verify_and_adjudicate("HALLUCINATED", "Gone [E1]. See [E9].", L, [LB], [])[0], None)
        r, _ = T.run([T.claims_reply(T.LB_SYM), T.call("find_symbol", "C1", name="chunk_decode"),
                      T.verdict("HALLUCINATED", "chunk_decode does not exist [E1]. Also [E9].")],
                     repo=T.repo_with(MISSING))
        self.assertEqual(r["verdict"], "UNVERIFIED")
        self.assertIn("E9", " ".join(r["trace"][-1]["finalize_events"]))

    def test_hook_returns_two_values(self):
        L = ledger_of(T.repo_with(MISSING), [("find_symbol", {"name": "chunk_decode"})])
        out = cv.verify_and_adjudicate("HALLUCINATED", "chunk_decode does not exist [E1].", L, [LB], [])
        self.assertEqual(out, ("HALLUCINATED", "chunk_decode does not exist [E1]."))


if __name__ == "__main__":
    unittest.main()
