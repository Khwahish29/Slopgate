
"""Unit tests for the SlopGate evaluation harness."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from slopgate.agent_layer.baselines.base import Skipped
from slopgate.evaluation.harness import evaluate, save_results


class FakeSystem:
    def triage(self, report_path, ws, repo):
        return {
            "verdict": "HALLUCINATED",
            "confidence": 0.9,
            "tool_calls": 2,
            "tokens": 0,
            "latency_s": 0.01,
            "trace": [],
        }


class ErrorSystem:
    def triage(self, report_path, ws, repo):
        raise RuntimeError("Simulated failure")


class SkippedSystem:
    def triage(self, report_path, ws, repo):
        raise Skipped("API credentials unavailable")


class InvalidVerdictSystem:
    def triage(self, report_path, ws, repo):
        return {"verdict": "UNKNOWN"}


class InvalidResultSystem:
    def triage(self, report_path, ws, repo):
        return "HALLUCINATED"


class TestEvaluationHarness(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()

        self.report = Path(self.tmp.name) / "report.md"
        self.report.write_text("Test report", encoding="utf-8")

        self.item = {
            "id": "test-001",
            "gold": "HALLUCINATED",
            "tier": "T1",
            "repo": str(self.repo),
            "report_path": str(self.report),
            "expected_verdict": "HALLUCINATED",
        }

    # Existing tests

    @patch("slopgate.evaluation.harness.build")
    def test_successful_evaluation(self, mock_build):
        mock_build.return_value = FakeSystem()

        rows = evaluate([self.item], "fake")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[0]["verdict"], "HALLUCINATED")
        self.assertEqual(rows[0]["tool_calls"], 2)

    @patch("slopgate.evaluation.harness.build")
    def test_system_failure(self, mock_build):
        mock_build.return_value = ErrorSystem()

        rows = evaluate([self.item], "broken")

        self.assertEqual(rows[0]["status"], "error")
        self.assertIn("Simulated failure", rows[0]["error"])

    @patch("slopgate.evaluation.harness.build")
    def test_missing_report(self, mock_build):
        mock_build.return_value = FakeSystem()

        item = dict(self.item)
        item["report_path"] = str(self.repo / "missing.md")

        rows = evaluate([item], "fake")

        self.assertEqual(rows[0]["status"], "error")
        self.assertIn("FileNotFoundError", rows[0]["error"])

    @patch("slopgate.evaluation.harness.build")
    def test_limit(self, mock_build):
        mock_build.return_value = FakeSystem()

        rows = evaluate([self.item, self.item], "fake", limit=1)

        self.assertEqual(len(rows), 1)

    def test_save_results(self):
        rows = [{
            "id": "test-001",
            "status": "ok",
            "expected_verdict": "HALLUCINATED",
            "verdict": "HALLUCINATED",
            "tool_calls": 2,
            "tokens": 0,
            "latency_s": 0.01,
        }]

        output = Path(self.tmp.name) / "results"
        metrics = save_results(rows, output, "fake")

        self.assertTrue((output / "fake_metrics.json").exists())
        self.assertTrue((output / "fake_predictions.jsonl").exists())
        self.assertEqual(metrics["accuracy"], 1.0)

    # Additional tests

    @patch("slopgate.evaluation.harness.build")
    def test_skipped_during_system_build(self, mock_build):
        mock_build.side_effect = Skipped("Missing API key")

        rows = evaluate([self.item], "b2")

        self.assertEqual(rows[0]["status"], "skipped")
        self.assertIsNone(rows[0]["verdict"])
        self.assertIn("Missing API key", rows[0]["error"])
        self.assertEqual(rows[0]["tier"], "T1")
        self.assertEqual(rows[0]["repo"], str(self.repo))

    @patch("slopgate.evaluation.harness.build")
    def test_skipped_during_triage(self, mock_build):
        mock_build.return_value = SkippedSystem()

        rows = evaluate([self.item], "b2")

        self.assertEqual(rows[0]["status"], "skipped")
        self.assertIn(
            "API credentials unavailable",
            rows[0]["error"],
        )

    @patch("slopgate.evaluation.harness.build")
    def test_invalid_verdict(self, mock_build):
        mock_build.return_value = InvalidVerdictSystem()

        rows = evaluate([self.item], "invalid")

        self.assertEqual(rows[0]["status"], "error")
        self.assertIn("Invalid verdict", rows[0]["error"])

    @patch("slopgate.evaluation.harness.build")
    def test_invalid_result_type(self, mock_build):
        mock_build.return_value = InvalidResultSystem()

        rows = evaluate([self.item], "invalid")

        self.assertEqual(rows[0]["status"], "error")
        self.assertIn(
            "must return a dictionary",
            rows[0]["error"],
        )

    @patch("slopgate.evaluation.harness.Workspace")
    @patch("slopgate.evaluation.harness.build")
    def test_workspace_reuse(self, mock_build, mock_workspace):
        mock_build.return_value = FakeSystem()

        second_item = dict(self.item)
        second_item["id"] = "test-002"

        rows = evaluate([self.item, second_item], "fake")

        self.assertEqual(len(rows), 2)
        self.assertTrue(
            all(row["status"] == "ok" for row in rows)
        )
        mock_workspace.assert_called_once_with(str(self.repo))

    @patch("slopgate.evaluation.harness.Workspace")
    @patch("slopgate.evaluation.harness.build")
    def test_workspace_cleanup_on_success(
        self, mock_build, mock_workspace
    ):
        mock_build.return_value = FakeSystem()

        workspace = MagicMock()
        mock_workspace.return_value = workspace

        evaluate([self.item], "fake")

        workspace.close.assert_called_once()

    @patch("slopgate.evaluation.harness.Workspace")
    @patch("slopgate.evaluation.harness.build")
    def test_workspace_cleanup_on_failure(
        self, mock_build, mock_workspace
    ):
        mock_build.return_value = ErrorSystem()

        workspace = MagicMock()
        mock_workspace.return_value = workspace

        rows = evaluate([self.item], "broken")

        self.assertEqual(rows[0]["status"], "error")
        workspace.close.assert_called_once()

    def test_trace_json_serialization(self):
        rows = [{
            "id": "test-001",
            "status": "ok",
            "expected_verdict": "HALLUCINATED",
            "verdict": "HALLUCINATED",
            "trace": [
                {
                    "step": 1,
                    "tool": "find_symbol",
                    "result": "CONTRADICTION",
                },
                {
                    "step": 2,
                    "tool": "resolve_tag",
                    "result": "GROUND",
                },
            ],
        }]

        output = Path(self.tmp.name) / "results"
        save_results(rows, output, "fake")

        predictions_file = output / "fake_predictions.jsonl"

        saved_rows = [
            json.loads(line)
            for line in predictions_file.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

        self.assertEqual(len(saved_rows), 1)
        self.assertEqual(
            saved_rows[0]["trace"][0]["tool"],
            "find_symbol",
        )
        self.assertEqual(
            saved_rows[0]["trace"][1]["result"],
            "GROUND",
        )


if __name__ == "__main__":
    unittest.main()
