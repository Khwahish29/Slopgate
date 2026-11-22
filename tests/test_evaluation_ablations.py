"""Unit tests for the SlopGate ablation runner."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopgate.evaluation.ablations import (
    ABLATIONS,
    register_systems,
    run_ablations,
)


class TestAblationRunner(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.data = self.root / "dataset.jsonl"
        self.output = self.root / "results"

        self.items = [
            {
                "id": "r1",
                "repo": "fixture",
                "gold": "HALLUCINATED",
                "report": "Example report 1",
            },
            {
                "id": "r2",
                "repo": "fixture",
                "gold": "NOT_HALLUCINATED",
                "report": "Example report 2",
            },
        ]

        self.data.write_text(
            "".join(json.dumps(x) + "\n" for x in self.items),
            encoding="utf-8",
        )

    def fake_metrics(self):
        return {
            "total": 2,
            "completed": 2,
            "accuracy": 1.0,
            "errors": 0,
            "skipped": 0,
        }

    def test_four_ablations_defined(self):
        self.assertEqual(len(ABLATIONS), 4)
        self.assertEqual(len(set(ABLATIONS)), 4)

    def test_all_ablations_registered(self):
        from slopgate.agent_layer.baselines.base import REGISTRY

        register_systems()

        for name in ABLATIONS:
            self.assertIn(name, REGISTRY)
            self.assertTrue(REGISTRY[name].needs_llm)

    def test_empty_systems_rejected(self):
        with self.assertRaises(ValueError):
            run_ablations(self.data, self.output, systems=[])

    def test_duplicate_systems_rejected(self):
        with self.assertRaises(ValueError):
            run_ablations(
                self.data,
                self.output,
                systems=[ABLATIONS[0], ABLATIONS[0]],
            )

    def test_unknown_system_rejected(self):
        with self.assertRaises(ValueError):
            run_ablations(
                self.data,
                self.output,
                systems=["not_an_ablation"],
            )

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            run_ablations(
                self.data,
                self.output,
                systems=[ABLATIONS[0]],
                limit=0,
            )

    def test_empty_dataset_rejected(self):
        self.data.write_text("", encoding="utf-8")

        with self.assertRaises(ValueError):
            run_ablations(
                self.data,
                self.output,
                systems=[ABLATIONS[0]],
            )

    @patch("slopgate.evaluation.ablations.run_resumable")
    def test_single_ablation(self, mock_run):
        mock_run.return_value = self.fake_metrics()

        result = run_ablations(
            self.data,
            self.output,
            systems=[ABLATIONS[0]],
        )

        self.assertIn(ABLATIONS[0], result)
        self.assertEqual(mock_run.call_count, 1)

        self.assertTrue(
            (self.output / "ablation_summary.json").exists()
        )

    @patch("slopgate.evaluation.ablations.run_resumable")
    def test_limit_passed_to_runner(self, mock_run):
        mock_run.return_value = self.fake_metrics()

        run_ablations(
            self.data,
            self.output,
            systems=[ABLATIONS[0]],
            limit=1,
        )

        args, kwargs = mock_run.call_args
        self.assertEqual(len(args[0]), 1)
        self.assertEqual(args[0][0]["id"], "r1")

    @patch("slopgate.evaluation.ablations.run_resumable")
    def test_retry_errors_disabled(self, mock_run):
        mock_run.return_value = self.fake_metrics()

        run_ablations(
            self.data,
            self.output,
            systems=[ABLATIONS[0]],
            retry_errors=False,
        )

        self.assertFalse(
            mock_run.call_args.kwargs["retry_errors"]
        )

    @patch("slopgate.evaluation.ablations.aggregate")
    @patch("slopgate.evaluation.ablations.run_resumable")
    def test_multiple_ablations_aggregated(
        self, mock_run, mock_aggregate
    ):
        mock_run.return_value = self.fake_metrics()

        result = run_ablations(
            self.data,
            self.output,
            systems=list(ABLATIONS[:2]),
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(mock_run.call_count, 2)
        mock_aggregate.assert_called_once()

    @patch("slopgate.evaluation.ablations.aggregate")
    @patch("slopgate.evaluation.ablations.run_resumable")
    def test_summary_contains_all_systems(
        self, mock_run, mock_aggregate
    ):
        mock_run.return_value = self.fake_metrics()

        run_ablations(
            self.data,
            self.output,
            systems=list(ABLATIONS[:2]),
        )

        summary = json.loads(
            (self.output / "ablation_summary.json").read_text()
        )

        self.assertEqual(set(summary), set(ABLATIONS[:2]))


if __name__ == "__main__":
    unittest.main()
