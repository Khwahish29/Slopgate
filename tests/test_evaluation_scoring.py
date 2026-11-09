
import unittest

from slopgate.evaluation.scoring import (
    expected_label,
    score_predictions,
)


class TestEvaluationScoring(unittest.TestCase):

    def test_gold_mapping(self):
        self.assertEqual(
            expected_label({"gold": "NOT_HALLUCINATED"}),
            "UNVERIFIED",
        )
        self.assertEqual(
            expected_label({"gold": "HALLUCINATED"}),
            "HALLUCINATED",
        )

    def test_perfect_predictions(self):
        rows = [
            {
                "status": "ok",
                "expected_verdict": "HALLUCINATED",
                "verdict": "HALLUCINATED",
                "tool_calls": 3,
                "tokens": 0,
                "latency_s": 0.2,
            },
            {
                "status": "ok",
                "expected_verdict": "UNVERIFIED",
                "verdict": "UNVERIFIED",
                "tool_calls": 5,
                "tokens": 0,
                "latency_s": 0.4,
            },
        ]

        result = score_predictions(rows)

        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["coverage"], 1.0)
        self.assertEqual(result["correct"], 2)
        self.assertEqual(result["mean_tool_calls"], 4)

    def test_skipped_not_scored(self):
        rows = [
            {
                "status": "ok",
                "expected_verdict": "HALLUCINATED",
                "verdict": "HALLUCINATED",
            },
            {
                "status": "skipped",
                "expected_verdict": "UNVERIFIED",
                "verdict": None,
            },
        ]

        result = score_predictions(rows)

        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["coverage"], 0.5)
        self.assertEqual(result["skipped"], 1)

    def test_wrong_prediction(self):
        rows = [{
            "status": "ok",
            "expected_verdict": "HALLUCINATED",
            "verdict": "UNVERIFIED",
        }]

        result = score_predictions(rows)

        self.assertEqual(result["accuracy"], 0.0)
        self.assertEqual(result["correct"], 0)

    def test_invalid_verdict(self):
        rows = [{
            "status": "ok",
            "expected_verdict": "HALLUCINATED",
            "verdict": "INVALID",
        }]

        with self.assertRaises(ValueError):
            score_predictions(rows)


if __name__ == "__main__":
    unittest.main()
