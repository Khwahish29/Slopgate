"""Tests for the resumable evaluation runner."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopgate.evaluation.resume import run_resumable


class TestResumableEvaluation(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "results"
        self.fingerprint = "test-dataset-sha256"

        self.items = [
            {
                "id": "report-001",
                "gold": "HALLUCINATED",
                "expected_verdict": "HALLUCINATED",
                "repo": "test-repo",
                "tier": "T1",
            },
            {
                "id": "report-002",
                "gold": "NOT_HALLUCINATED",
                "expected_verdict": "UNVERIFIED",
                "repo": "test-repo",
                "tier": "T4",
            },
        ]

    def fake_evaluate(self, items, system_name):
        item = items[0]
        return [{
            "id": item["id"],
            "system": system_name,
            "status": "ok",
            "gold": item["gold"],
            "expected_verdict": item["expected_verdict"],
            "verdict": item["expected_verdict"],
            "tool_calls": 2,
            "tokens": 0,
            "latency_s": 0.01,
        }]

    @patch("slopgate.evaluation.resume.evaluate")
    def test_first_run(self, mock_evaluate):
        mock_evaluate.side_effect = self.fake_evaluate

        metrics = run_resumable(
            self.items, "b1", self.output, self.fingerprint
        )

        self.assertEqual(metrics["completed"], 2)
        self.assertEqual(metrics["accuracy"], 1.0)
        self.assertEqual(mock_evaluate.call_count, 2)

        self.assertTrue(
            (self.output / "b1_predictions.jsonl").exists()
        )
        self.assertTrue(
            (self.output / "b1_metrics.json").exists()
        )
        self.assertTrue(
            (self.output / "b1_run.json").exists()
        )

    @patch("slopgate.evaluation.resume.evaluate")
    def test_resume_skips_successful_reports(self, mock_evaluate):
        mock_evaluate.side_effect = self.fake_evaluate

        run_resumable(
            self.items, "b1", self.output, self.fingerprint
        )

        mock_evaluate.reset_mock()

        metrics = run_resumable(
            self.items, "b1", self.output, self.fingerprint
        )

        mock_evaluate.assert_not_called()
        self.assertEqual(metrics["completed"], 2)

    @patch("slopgate.evaluation.resume.evaluate")
    def test_failed_report_is_retried(self, mock_evaluate):
        attempts = {}

        def evaluate_with_failure(items, system_name):
            report_id = items[0]["id"]
            attempts[report_id] = attempts.get(report_id, 0) + 1

            if report_id == "report-001" and attempts[report_id] == 1:
                return [{
                    "id": report_id,
                    "system": system_name,
                    "status": "error",
                    "expected_verdict": "HALLUCINATED",
                    "verdict": None,
                    "error": "Temporary failure",
                }]

            return self.fake_evaluate(items, system_name)

        mock_evaluate.side_effect = evaluate_with_failure

        first = run_resumable(
            self.items, "b1", self.output, self.fingerprint
        )
        self.assertEqual(first["errors"], 1)

        second = run_resumable(
            self.items, "b1", self.output, self.fingerprint
        )

        self.assertEqual(second["errors"], 0)
        self.assertEqual(second["completed"], 2)
        self.assertEqual(attempts["report-001"], 2)
        self.assertEqual(attempts["report-002"], 1)

    @patch("slopgate.evaluation.resume.evaluate")
    def test_no_retry_errors(self, mock_evaluate):
        mock_evaluate.return_value = [{
            "id": "report-001",
            "system": "b1",
            "status": "error",
            "expected_verdict": "HALLUCINATED",
            "verdict": None,
            "error": "Failure",
        }]

        run_resumable(
            self.items[:1], "b1", self.output, self.fingerprint
        )

        mock_evaluate.reset_mock()

        result = run_resumable(
            self.items[:1],
            "b1",
            self.output,
            self.fingerprint,
            retry_errors=False,
        )

        mock_evaluate.assert_not_called()
        self.assertEqual(result["errors"], 1)

    @patch("slopgate.evaluation.resume.evaluate")
    def test_no_duplicate_predictions(self, mock_evaluate):
        mock_evaluate.side_effect = self.fake_evaluate

        for _ in range(3):
            run_resumable(
                self.items, "b1", self.output, self.fingerprint
            )

        path = self.output / "b1_predictions.jsonl"
        rows = [
            json.loads(line)
            for line in path.read_text().splitlines()
        ]

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            len(set(row["id"] for row in rows)), 2
        )

    @patch("slopgate.evaluation.resume.evaluate")
    def test_dataset_mismatch_rejected(self, mock_evaluate):
        mock_evaluate.side_effect = self.fake_evaluate

        run_resumable(
            self.items, "b1", self.output, self.fingerprint
        )

        with self.assertRaises(ValueError):
            run_resumable(
                self.items,
                "b1",
                self.output,
                "different-dataset-sha256",
            )

    def test_duplicate_dataset_ids_rejected(self):
        duplicate_items = [self.items[0], self.items[0]]

        with self.assertRaises(ValueError):
            run_resumable(
                duplicate_items,
                "b1",
                self.output,
                self.fingerprint,
            )

    @patch("slopgate.evaluation.resume.evaluate")
    def test_interrupted_run_can_resume(self, mock_evaluate):
        calls = {"count": 0}

        def interrupted_evaluate(items, system_name):
            calls["count"] += 1

            if calls["count"] == 2:
                raise KeyboardInterrupt()

            return self.fake_evaluate(items, system_name)

        mock_evaluate.side_effect = interrupted_evaluate

        with self.assertRaises(KeyboardInterrupt):
            run_resumable(
                self.items, "b1", self.output, self.fingerprint
            )

        saved = (
            self.output / "b1_predictions.jsonl"
        ).read_text().splitlines()

        self.assertEqual(len(saved), 1)

        mock_evaluate.side_effect = self.fake_evaluate
        mock_evaluate.reset_mock()

        result = run_resumable(
            self.items, "b1", self.output, self.fingerprint
        )

        self.assertEqual(mock_evaluate.call_count, 1)
        self.assertEqual(result["completed"], 2)


if __name__ == "__main__":
    unittest.main()
