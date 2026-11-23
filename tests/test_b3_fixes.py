"""B3 fixes: links are not file claims, b3_rules reads like B1, failures are visible. Offline."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from slopgate.agent_layer.baselines import b3_fixed, build                # noqa: E402
from slopgate.agent_layer.llm import (LLMBackend, ModelError, RateLimitError, ScriptedClient,   # noqa: E402
                                      looks_like_url, validate_claims)
from slopgate.agent_layer.prose_extract import ProseRuleBackend            # noqa: E402
from slopgate.agent_layer.tools import Workspace                           # noqa: E402

SRC = "int\nchunk_decode(char *p)\n{\n  return *p;\n}\n"


def repo():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "lib"))
    open(os.path.join(d, "lib", "chunk.c"), "w").write(SRC)
    return d


def write(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
    f.write(text)
    f.close()
    return f.name


# a header-style report whose last line is a CWE link: the old extractor read ".../787.h" out of ".html"
LINKED = ("# Overflow in chunk_decode\n\n- **Function:** `chunk_decode()`\n- **Component:** `lib/chunk.c`\n\n"
          "Reference: https://cwe.mitre.org/data/definitions/787.html\n")


class Links(unittest.TestCase):
    def test_host_names_and_urls_are_not_paths(self):
        self.assertTrue(looks_like_url("cwe.mitre.org/data/definitions/787.h", "see cwe.mitre.org/data/definitions/787.h"))
        self.assertTrue(looks_like_url("lib/a.c", "https://github.com/o/r/blob/main/lib/a.c"))
        self.assertFalse(looks_like_url("lib/a.c", "in lib/a.c"))
        self.assertFalse(looks_like_url("lib/a.c", "https://example.org/x and then lib/a.c"))   # one real mention
        self.assertFalse(looks_like_url("src/cookie.c", "src/cookie.c"))

    def test_validate_claims_drops_links_keeps_files(self):
        text = "CWE link cwe.mitre.org/data/definitions/787.h and lib/chunk.c"
        raw = [{"type": "path", "value": "cwe.mitre.org/data/definitions/787.h", "span": text, "role": "supporting"},
               {"type": "path", "value": "lib/chunk.c", "span": text, "role": "supporting"}]
        good, bad = validate_claims(raw, text)
        self.assertEqual([c["value"] for c in good], ["lib/chunk.c"])
        self.assertIn("web address", bad[0]["why"])

    def test_real_report_with_a_cwe_link_is_not_dismissed(self):
        d = repo()
        r = build("b3_rules").triage(write(LINKED), Workspace(d), d)
        self.assertNotEqual(r["verdict"], "HALLUCINATED")
        self.assertFalse([e for e in r["ledger"] if "mitre" in json.dumps(e["args"])])


class Reader(unittest.TestCase):
    def test_b3_rules_reads_with_the_b1_extractor(self):
        self.assertIsInstance(build("b3_rules").backend, ProseRuleBackend)
        self.assertIsInstance(b3_fixed.FLOOR, ProseRuleBackend)

    def test_prose_report_yields_claims_for_b3_rules(self):
        d = repo()
        text = "The overflow is in chunk_decode() in lib/chunk.c at line 4; it copies without a bound.\n"
        r = build("b3_rules").triage(write(text), Workspace(d), d)
        self.assertTrue([c for c in r["claims"] if c["type"] == "symbol" and c["value"] == "chunk_decode"])
        self.assertEqual(r["extraction"], "floor")


class Visibility(unittest.TestCase):
    def _sys(self, client):
        s = b3_fixed.FixedLLM.__new__(b3_fixed.FixedLLM)
        s.backend = LLMBackend(client, "some-model")
        return s

    def test_failed_extraction_is_counted_and_falls_back(self):
        d = repo()
        r = self._sys(ScriptedClient(["no json", "still no json", "x", "y"])).triage(write(LINKED), Workspace(d), d)
        self.assertEqual(r["extraction"], "floor")
        self.assertGreaterEqual(r["model_errors"], 1)

    def test_rate_limit_during_extraction_falls_back_and_reports_it(self):
        class Limited(ScriptedClient):
            retries, rate_limited = 0, 0

            def chat(self, messages, ref=""):
                self.rate_limited += 1
                raise RateLimitError("HTTPError 429 (Retry-After: 4)", 4.0)

        d = repo()
        r = self._sys(Limited([])).triage(write(LINKED), Workspace(d), d)
        self.assertEqual(r["extraction"], "floor")
        self.assertEqual(r["rate_limited"], 2)                 # tried twice, then the rule reader took over
        self.assertNotEqual(r["verdict"], "HALLUCINATED")      # an outage never turns into a dismissal

    def test_rules_system_reports_zero_model_activity(self):
        d = repo()
        r = build("b3_rules").triage(write(LINKED), Workspace(d), d)
        self.assertEqual((r["model_calls"], r["model_errors"], r["retries"], r["rate_limited"]), (0, 0, 0, 0))

    def test_description_names_the_model_actually_used(self):
        env = {"XAI_API_KEY": "k", "XAI_BASE_URL": "http://x", "XAI_MODEL": "openai/gpt-oss-120b"}
        with mock.patch.dict(os.environ, env, clear=True):
            s = build("b3_llm")
        self.assertIn("openai/gpt-oss-120b", s.description)
        self.assertNotIn("Grok", s.description)


if __name__ == "__main__":
    unittest.main()
