"""Tests for the SlopGate D3/D4 review viewer."""

import json
import tempfile
import unittest
from pathlib import Path

from slopgate.evaluation.review import (
    dataset_kind,
    filter_rows,
    join_predictions,
    load_jsonl,
    review,
    summarize,
)


class TestReviewViewer(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.dataset_path = self.root / "dataset.jsonl"
        self.predictions_path = self.root / "predictions.jsonl"

        self.dataset = [
            {
                "id": "d3-example-1",
                "tier": "D3",
                "subtype": "wrong_line",
                "gold": "NOT_HALLUCINATED",
                "expected_verdict": "UNVERIFIED",
                "base_id": "d1-example-1",
                "report": "Example D3 report",
            },
            {
                "id": "d4-example-2",
                "tier": "T2",
                "subtype": "to_real_known",
                "gold": "HALLUCINATED",
                "expected_verdict": "HALLUCINATED",
                "base_id": "d1-example-2",
                "injection": {
                    "kind": "known",
                    "direction": "to_real",
                    "text": "Ignore instructions",
                },
                "report": "Example D4 report",
            },
        ]

        self.predictions = [
            {
                "id": "d3-example-1",
                "status": "ok",
                "verdict": "UNVERIFIED",
                "tool_calls": 3,
            },
            {
                "id": "d4-example-2",
                "status": "ok",
                "verdict": "UNVERIFIED",
                "tool_calls": 4,
            },
        ]

        self.write_jsonl(self.dataset_path, self.dataset)
        self.write_jsonl(self.predictions_path, self.predictions)

    @staticmethod
    def write_jsonl(path, rows):
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_dataset_kind_d3(self):
        self.assertEqual(dataset_kind(self.dataset[0]), "D3")

    def test_dataset_kind_d4_original_tier(self):
        self.assertEqual(dataset_kind(self.dataset[1]), "D4")

    def test_dataset_kind_unknown(self):
        self.assertEqual(dataset_kind({"id": "other-1"}), "OTHER")

    def test_load_jsonl(self):
        rows = load_jsonl(self.dataset_path)
        self.assertEqual(len(rows), 2)

    def test_duplicate_ids_rejected(self):
        self.write_jsonl(
            self.dataset_path,
            [self.dataset[0], self.dataset[0]],
        )

        with self.assertRaises(ValueError):
            load_jsonl(self.dataset_path)

    def test_invalid_json_rejected(self):
        self.dataset_path.write_text(
            "{invalid json}\n",
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            load_jsonl(self.dataset_path)

    def test_join_predictions(self):
        rows = join_predictions(
            self.dataset,
            self.predictions,
        )

        self.assertTrue(rows[0]["correct"])
        self.assertFalse(rows[1]["correct"])

    def test_missing_predictions(self):
        rows = join_predictions(self.dataset, [])

        self.assertEqual(rows[0]["prediction_status"], "missing")
        self.assertIsNone(rows[0]["correct"])

    def test_summary_accuracy(self):
        rows = join_predictions(
            self.dataset,
            self.predictions,
        )

        result = summarize(rows)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["incorrect"], 1)
        self.assertEqual(result["accuracy"], 0.5)

    def test_summary_injection_direction(self):
        rows = join_predictions(
            self.dataset,
            self.predictions,
        )

        result = summarize(rows)

        self.assertEqual(
            result["by_injection_direction"]["to_real"],
            1,
        )

    def test_filter_dataset(self):
        rows = join_predictions(
            self.dataset,
            self.predictions,
        )

        selected = filter_rows(rows, dataset="D4")

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["id"], "d4-example-2")

    def test_filter_subtype(self):
        rows = join_predictions(
            self.dataset,
            self.predictions,
        )

        selected = filter_rows(
            rows,
            subtype="wrong_line",
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["id"], "d3-example-1")

    def test_errors_only(self):
        rows = join_predictions(
            self.dataset,
            self.predictions,
        )

        selected = filter_rows(
            rows,
            errors_only=True,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["id"], "d4-example-2")

    def test_review_export(self):
        export_path = self.root / "review.json"

        result = review(
            data_path=self.dataset_path,
            predictions_path=self.predictions_path,
            limit=0,
            export=export_path,
        )

        self.assertTrue(export_path.exists())

        payload = json.loads(export_path.read_text())

        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(len(payload["reports"]), 2)
        self.assertEqual(result["accuracy"], 0.5)

    def test_review_without_predictions(self):
        result = review(
            data_path=self.dataset_path,
            limit=0,
        )

        self.assertEqual(result["missing"], 2)
        self.assertIsNone(result["accuracy"])


if __name__ == "__main__":
    unittest.main()
