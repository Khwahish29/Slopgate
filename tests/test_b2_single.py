
"""Offline tests for the B2 single-call LLM baseline."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopgate.agent_layer.baselines import build
from slopgate.agent_layer.baselines.base import Skipped
from slopgate.agent_layer.baselines.b2_single import (
    B2Grok,
    B2Muse,
    collect_named_files,
    named_paths,
    parse_verdict,
)
from slopgate.agent_layer.llm import ScriptedClient


class TestB2Single(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

        source = self.repo / "internal"
        source.mkdir()

        (source / "parser.go").write_text(
            "package internal\nfunc ParseInput() {}\n",
            encoding="utf-8",
        )

        self.report = self.root / "report.md"
        self.report.write_text(
            "The function ParseInput in "
            "internal/parser.go is vulnerable.",
            encoding="utf-8",
        )

    def test_registration(self):
        self.assertIsInstance(
            build("b2_grok")
            if False else B2Grok(
                client=ScriptedClient([])
            ),
            B2Grok,
        )
        self.assertIsInstance(
            B2Muse(client=ScriptedClient([])),
            B2Muse,
        )

    def test_named_paths(self):
        paths = named_paths(
            "Check internal/parser.go and internal/parser.go"
        )
        self.assertEqual(
            paths,
            ["internal/parser.go"],
        )

    def test_collect_named_files(self):
        report = self.report.read_text(
            encoding="utf-8"
        )
        files = collect_named_files(
            report,
            str(self.repo),
        )

        self.assertEqual(len(files), 1)
        self.assertEqual(
            files[0]["path"],
            "internal/parser.go",
        )
        self.assertIn(
            "ParseInput",
            files[0]["content"],
        )

    def test_missing_named_file(self):
        files = collect_named_files(
            "Look at internal/missing.go",
            str(self.repo),
        )
        self.assertEqual(files, [])

    def test_parse_valid_verdict(self):
        verdict, confidence, reason = parse_verdict(
            json.dumps({
                "verdict": "UNVERIFIED",
                "confidence": 0.7,
                "reason": "Insufficient evidence",
            })
        )

        self.assertEqual(verdict, "UNVERIFIED")
        self.assertEqual(confidence, 0.7)
        self.assertEqual(reason, "Insufficient evidence")

    def test_reject_invalid_verdict(self):
        with self.assertRaises(ValueError):
            parse_verdict(
                '{"verdict":"UNKNOWN"}'
            )

    def test_reject_invalid_confidence(self):
        with self.assertRaises(ValueError):
            parse_verdict(
                '{"verdict":"UNVERIFIED","confidence":2}'
            )

    def test_single_model_call(self):
        client = ScriptedClient([
            json.dumps({
                "verdict": "UNVERIFIED",
                "confidence": 0.8,
                "reason": "Limited evidence",
            })
        ])

        system = B2Grok(client=client)

        result = system.triage(
            str(self.report),
            None,
            str(self.repo),
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(result["model_calls"], 1)
        self.assertEqual(result["tool_calls"], 0)
        self.assertEqual(result["verdict"], "UNVERIFIED")
        self.assertEqual(
            result["trace"][0]["named_files"],
            ["internal/parser.go"],
        )

    def test_invalid_reply_does_not_retry(self):
        client = ScriptedClient([
            "not valid JSON",
            '{"verdict":"UNVERIFIED"}',
        ])

        system = B2Grok(client=client)

        with self.assertRaises(ValueError):
            system.triage(
                str(self.report),
                None,
                str(self.repo),
            )

        self.assertEqual(client.calls, 1)

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_credentials_skips(self):
        with self.assertRaises(Skipped):
            B2Grok()

    def test_no_named_files_still_calls_model(self):
        self.report.write_text(
            "There may be a vulnerability.",
            encoding="utf-8",
        )

        client = ScriptedClient([
            '{"verdict":"UNVERIFIED","confidence":0.2,'
            '"reason":"No code context"}'
        ])

        result = B2Grok(client=client).triage(
            str(self.report),
            None,
            str(self.repo),
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(
            result["trace"][0]["named_files"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
