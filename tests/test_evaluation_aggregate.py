"""Tests for cross-system evaluation aggregation."""

import json
import tempfile
import unittest
from pathlib import Path

from slopgate.evaluation.aggregate import aggregate


class TestEvaluationAggregate(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.input_dir = Path(self.tmp.name) / "input"
        self.output_dir = Path(self.tmp.name) / "output"
        self.input_dir.mkdir()

        self.rows = [
            {
                "id": "report-001",
                "system": "b0",
                "status": "ok",
                "expected_verdict": "HALLUCINATED",
                "verdict": "HALLUCINATED",
            },
            {
                "id": "report-002",
                "system": "b0",
                "status": "ok",
                "expected_verdict": "UNVERIFIED",
                "verdict": "UNVERIFIED",
            },
        ]

    def write_predictions(self, system, rows):
        path = self.input_dir / (
            system + "_predictions.jsonl"
        )
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def write_metadata(
        self,
        system,
        fingerprint="dataset-123",
        ids=None,
    ):
        if ids is None:
            ids = ["report-001", "report-002"]

        metadata = {
            "system": system,
            "dataset_sha256": fingerprint,
            "report_count": len(ids),
            "report_ids": ids,
        }

        path = self.input_dir / (system + "_run.json")
        path.write_text(json.dumps(metadata), encoding="utf-8")

    def rows_for(self, system):
        return [
            dict(row, system=system)
            for row in self.rows
        ]

    def test_successful_aggregation(self):
        self.write_predictions("b0", self.rows_for("b0"))
        self.write_predictions("b1", self.rows_for("b1"))

        result = aggregate(self.input_dir, self.output_dir)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["accuracy"], 1.0)
        self.assertEqual(result[1]["accuracy"], 1.0)

        self.assertTrue(
            (self.output_dir / "comparison.csv").exists()
        )
        self.assertTrue(
            (self.output_dir / "comparison.json").exists()
        )

    def test_matching_metadata(self):
        self.write_predictions("b0", self.rows_for("b0"))
        self.write_predictions("b1", self.rows_for("b1"))

        self.write_metadata("b0")
        self.write_metadata("b1")

        result = aggregate(self.input_dir, self.output_dir)
        self.assertEqual(len(result), 2)

    def test_mismatched_fingerprint(self):
        self.write_predictions("b0", self.rows_for("b0"))
        self.write_predictions("b1", self.rows_for("b1"))

        self.write_metadata("b0", "dataset-A")
        self.write_metadata("b1", "dataset-B")

        with self.assertRaises(ValueError):
            aggregate(self.input_dir, self.output_dir)

    def test_mismatched_report_ids(self):
        self.write_predictions("b0", self.rows_for("b0"))
        self.write_predictions(
            "b1",
            self.rows_for("b1")[:1],
        )

        with self.assertRaises(ValueError):
            aggregate(self.input_dir, self.output_dir)

    def test_duplicate_predictions(self):
        rows = self.rows_for("b0")
        rows.append(dict(rows[0]))

        self.write_predictions("b0", rows)

        with self.assertRaises(ValueError):
            aggregate(self.input_dir, self.output_dir)

    def test_system_mismatch(self):
        self.write_predictions(
            "b0",
            self.rows_for("b1"),
        )

        with self.assertRaises(ValueError):
            aggregate(self.input_dir, self.output_dir)

    def test_mixed_metadata(self):
        self.write_predictions("b0", self.rows_for("b0"))
        self.write_predictions("b1", self.rows_for("b1"))

        self.write_metadata("b0")

        with self.assertRaises(ValueError):
            aggregate(self.input_dir, self.output_dir)

    def test_no_prediction_files(self):
        with self.assertRaises(ValueError):
            aggregate(self.input_dir, self.output_dir)

    def test_invalid_metadata_count(self):
        self.write_predictions("b0", self.rows_for("b0"))
        self.write_metadata("b0")

        path = self.input_dir / "b0_run.json"
        metadata = json.loads(path.read_text())
        metadata["report_count"] = 99
        path.write_text(json.dumps(metadata))

        with self.assertRaises(ValueError):
            aggregate(self.input_dir, self.output_dir)


if __name__ == "__main__":
    unittest.main()
