
"""Tests for the B0 grep baseline."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopgate.agent_layer.baselines import build
from slopgate.agent_layer.baselines.b0_grep import (
    B0Grep,
    grep_repository,
    extract_primary_symbol,
)


class TestB0Grep(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

        self.report = self.root / "report.md"
        self.report.write_text(
            "The function vulnerable_parser contains "
            "a security vulnerability.",
            encoding="utf-8",
        )

    def test_registered(self):
        system = build("b0")
        self.assertIsInstance(system, B0Grep)

    def test_grep_finds_symbol(self):
        (self.repo / "example.py").write_text(
            "def vulnerable_parser():\n    pass\n",
            encoding="utf-8",
        )

        found, checked = grep_repository(
            self.repo,
            "vulnerable_parser",
        )

        self.assertTrue(found)
        self.assertGreaterEqual(checked, 1)

    def test_grep_missing_symbol(self):
        (self.repo / "example.py").write_text(
            "def safe_parser():\n    pass\n",
            encoding="utf-8",
        )

        found, checked = grep_repository(
            self.repo,
            "vulnerable_parser",
        )

        self.assertFalse(found)
        self.assertEqual(checked, 1)

    def test_grep_skips_git_directory(self):
        git_dir = self.repo / ".git"
        git_dir.mkdir()

        (git_dir / "hidden.txt").write_text(
            "vulnerable_parser",
            encoding="utf-8",
        )

        found, checked = grep_repository(
            self.repo,
            "vulnerable_parser",
        )

        self.assertFalse(found)
        self.assertEqual(checked, 0)

    def test_missing_repository(self):
        with self.assertRaises(FileNotFoundError):
            grep_repository(
                self.root / "missing",
                "vulnerable_parser",
            )

    @patch(
        "slopgate.agent_layer.baselines.b0_grep."
        "extract_primary_symbol",
        return_value="vulnerable_parser",
    )
    def test_triage_symbol_found(self, mock_extract):
        (self.repo / "example.py").write_text(
            "def vulnerable_parser(): pass",
            encoding="utf-8",
        )

        result = B0Grep().triage(
            str(self.report),
            None,
            str(self.repo),
        )

        self.assertEqual(result["verdict"], "UNVERIFIED")
        self.assertTrue(result["symbol_found"])
        self.assertEqual(result["tool_calls"], 0)
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["tokens"], 0)

    @patch(
        "slopgate.agent_layer.baselines.b0_grep."
        "extract_primary_symbol",
        return_value="vulnerable_parser",
    )
    def test_triage_symbol_missing(self, mock_extract):
        (self.repo / "example.py").write_text(
            "def safe_parser(): pass",
            encoding="utf-8",
        )

        result = B0Grep().triage(
            str(self.report),
            None,
            str(self.repo),
        )

        self.assertEqual(
            result["verdict"],
            "HALLUCINATED",
        )
        self.assertFalse(result["symbol_found"])

    @patch(
        "slopgate.agent_layer.baselines.b0_grep."
        "extract_primary_symbol",
        return_value=None,
    )
    def test_triage_no_symbol(self, mock_extract):
        result = B0Grep().triage(
            str(self.report),
            None,
            str(self.repo),
        )

        self.assertEqual(result["verdict"], "UNVERIFIED")
        self.assertIsNone(result["symbol_found"])

    def test_output_structure(self):
        with patch(
            "slopgate.agent_layer.baselines.b0_grep."
            "extract_primary_symbol",
            return_value="vulnerable_parser",
        ):
            result = B0Grep().triage(
                str(self.report),
                None,
                str(self.repo),
            )

        for field in (
            "verdict",
            "confidence",
            "tool_calls",
            "tokens",
            "model_calls",
            "latency_s",
            "trace",
            "ledger",
            "rationale",
        ):
            self.assertIn(field, result)


if __name__ == "__main__":
    unittest.main()
