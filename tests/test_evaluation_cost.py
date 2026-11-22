"""Unit tests for SlopGate evaluation cost accounting."""

import json
import tempfile
import unittest
from pathlib import Path

from slopgate.evaluation.cost import (
    account_directory,
    account_system,
)


def make_row(
    report_id="r1",
    system="b1",
    expected="HALLUCINATED",
    verdict="HALLUCINATED",
    tokens=0,
    model_calls=0,
    tool_calls=2,
    latency=0.1,
    cost=None,
):
    return {
        "id": report_id,
        "system": system,
        "status": "ok",
        "expected_verdict": expected,
        "verdict": verdict,
        "tokens": tokens,
        "model_calls": model_calls,
        "tool_calls": tool_calls,
        "latency_s": latency,
        "cost_usd": cost,
    }


class TestCostAccounting(unittest.TestCase):

    def test_rule_based_zero_api_cost(self):
        result = account_system([make_row()], "b1")
        self.assertEqual(result["api_cost_usd"], 0)
        self.assertTrue(result["pricing_complete"])

    def test_recorded_api_cost(self):
        row = make_row(
            tokens=1000, model_calls=1, cost=0.002
        )
        result = account_system([row], "agent")
        self.assertAlmostEqual(result["api_cost_usd"], 0.002)
        self.assertEqual(result["recorded_cost_reports"], 1)

    def test_explicit_token_price(self):
        row = make_row(tokens=2000, model_calls=1)
        result = account_system(
            [row], "b2", usd_per_1k_tokens=0.001
        )
        self.assertAlmostEqual(result["api_cost_usd"], 0.002)
        self.assertEqual(result["estimated_cost_reports"], 1)

    def test_unknown_api_cost(self):
        row = make_row(tokens=1000, model_calls=1)
        result = account_system([row], "b2")
        self.assertIsNone(result["api_cost_usd"])
        self.assertEqual(result["unpriced_reports"], 1)

    def test_missing_token_count(self):
        row = make_row(tokens=None, model_calls=1)
        result = account_system([row], "b2")
        self.assertIsNone(result["total_tokens"])
        self.assertIsNone(result["api_cost_usd"])

    def test_usage_totals(self):
        rows = [
            make_row("r1", tokens=100, tool_calls=2, latency=0.1),
            make_row("r2", tokens=200, tool_calls=3, latency=0.3),
        ]
        result = account_system(rows, "b1")
        self.assertEqual(result["total_tokens"], 300)
        self.assertEqual(result["total_tool_calls"], 5)
        self.assertAlmostEqual(result["total_latency_s"], 0.4)
        self.assertAlmostEqual(result["mean_latency_s"], 0.2)

    def test_false_dismissal_penalty(self):
        row = make_row(
            expected="UNVERIFIED",
            verdict="HALLUCINATED",
        )
        result = account_system([row], "b1")
        self.assertEqual(result["false_dismissals"], 1)
        self.assertEqual(result["classification_cost_units"], 500)

    def test_missed_hallucination_penalty(self):
        row = make_row(
            expected="HALLUCINATED",
            verdict="UNVERIFIED",
        )
        result = account_system([row], "b1")
        self.assertEqual(result["missed_hallucinations"], 1)
        self.assertEqual(result["classification_cost_units"], 1)

    def test_negative_tokens_rejected(self):
        with self.assertRaises(ValueError):
            account_system(
                [make_row(tokens=-10)], "b1"
            )

    def test_negative_pricing_rejected(self):
        with self.assertRaises(ValueError):
            account_system(
                [make_row()], "b1",
                usd_per_1k_tokens=-0.01,
            )

    def test_directory_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input"
            output = Path(tmp) / "output"
            source.mkdir()

            path = source / "b1_predictions.jsonl"
            path.write_text(
                json.dumps(make_row()) + "\n",
                encoding="utf-8",
            )

            summaries = account_directory(source, output)

            self.assertEqual(len(summaries), 1)
            self.assertTrue(
                (output / "cost_summary.json").exists()
            )
            self.assertTrue(
                (output / "cost_summary.csv").exists()
            )

    def test_empty_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                account_directory(
                    Path(tmp), Path(tmp) / "output"
                )


if __name__ == "__main__":
    unittest.main()
