
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
