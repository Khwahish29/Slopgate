"""Unit tests for SlopGate statistical evaluation."""

import unittest

from slopgate.evaluation.stats import bootstrap_ci, mcnemar_test


def make_row(report_id, expected, verdict, status="ok"):
    return {
        "id": report_id,
        "status": status,
        "expected_verdict": expected,
        "verdict": verdict,
    }


class TestBootstrapCI(unittest.TestCase):

    def test_perfect_accuracy(self):
        rows = [
            make_row(str(i), "HALLUCINATED", "HALLUCINATED")
            for i in range(10)
        ]

        result = bootstrap_ci(rows, samples=100)

        self.assertEqual(result["estimate"], 1.0)
        self.assertEqual(result["lower"], 1.0)
        self.assertEqual(result["upper"], 1.0)
        self.assertEqual(result["n"], 10)

    def test_zero_accuracy(self):
        rows = [
            make_row(str(i), "HALLUCINATED", "UNVERIFIED")
            for i in range(10)
        ]

        result = bootstrap_ci(rows, samples=100)

        self.assertEqual(result["estimate"], 0.0)
        self.assertEqual(result["lower"], 0.0)
        self.assertEqual(result["upper"], 0.0)

    def test_mixed_accuracy(self):
        rows = [
            make_row("1", "HALLUCINATED", "HALLUCINATED"),
            make_row("2", "HALLUCINATED", "UNVERIFIED"),
            make_row("3", "UNVERIFIED", "UNVERIFIED"),
            make_row("4", "UNVERIFIED", "HALLUCINATED"),
        ]

        result = bootstrap_ci(rows, samples=500)

        self.assertEqual(result["estimate"], 0.5)
        self.assertLessEqual(result["lower"], 0.5)
        self.assertGreaterEqual(result["upper"], 0.5)

    def test_reproducibility(self):
        rows = [
            make_row(str(i), "HALLUCINATED",
                     "HALLUCINATED" if i % 2 == 0 else "UNVERIFIED")
            for i in range(20)
        ]

        first = bootstrap_ci(rows, samples=200, seed=42)
        second = bootstrap_ci(rows, samples=200, seed=42)

        self.assertEqual(first, second)

    def test_empty_rows(self):
        result = bootstrap_ci([], samples=100)

        self.assertIsNone(result["estimate"])
        self.assertIsNone(result["lower"])
        self.assertIsNone(result["upper"])
        self.assertEqual(result["n"], 0)

    def test_skipped_rows_excluded(self):
        rows = [
            make_row("1", "HALLUCINATED", "HALLUCINATED"),
            make_row("2", "HALLUCINATED", None, "skipped"),
        ]

        result = bootstrap_ci(rows, samples=100)

        self.assertEqual(result["n"], 1)
        self.assertEqual(result["estimate"], 1.0)

    def test_invalid_confidence(self):
        with self.assertRaises(ValueError):
            bootstrap_ci([], confidence=1.5)

    def test_invalid_samples(self):
        with self.assertRaises(ValueError):
            bootstrap_ci([], samples=0)


class TestMcNemar(unittest.TestCase):

    def test_identical_correct_predictions(self):
        rows = [
            make_row(str(i), "HALLUCINATED", "HALLUCINATED")
            for i in range(10)
        ]

        result = mcnemar_test(rows, rows)

        self.assertEqual(result["both_correct"], 10)
        self.assertEqual(result["discordant"], 0)
        self.assertEqual(result["p_value"], 1.0)

    def test_identical_wrong_predictions(self):
        rows = [
            make_row(str(i), "HALLUCINATED", "UNVERIFIED")
            for i in range(10)
        ]

        result = mcnemar_test(rows, rows)

        self.assertEqual(result["both_wrong"], 10)
        self.assertEqual(result["p_value"], 1.0)

    def test_known_exact_p_value(self):
        # A correct on all 6 reports; B wrong on all 6.
        # Exact two-sided p = 2 / 2^6 = 0.03125.
        a = [
            make_row(str(i), "HALLUCINATED", "HALLUCINATED")
            for i in range(6)
        ]
        b = [
            make_row(str(i), "HALLUCINATED", "UNVERIFIED")
            for i in range(6)
        ]

        result = mcnemar_test(a, b)

        self.assertEqual(result["a_only_correct"], 6)
        self.assertEqual(result["b_only_correct"], 0)
        self.assertAlmostEqual(result["p_value"], 0.03125)
        self.assertTrue(result["significant_0_05"])

    def test_balanced_disagreement(self):
        a = [
            make_row("1", "HALLUCINATED", "HALLUCINATED"),
            make_row("2", "HALLUCINATED", "UNVERIFIED"),
        ]
        b = [
            make_row("1", "HALLUCINATED", "UNVERIFIED"),
            make_row("2", "HALLUCINATED", "HALLUCINATED"),
        ]

        result = mcnemar_test(a, b)

        self.assertEqual(result["a_only_correct"], 1)
        self.assertEqual(result["b_only_correct"], 1)
        self.assertEqual(result["p_value"], 1.0)

    def test_mismatched_report_ids(self):
        a = [make_row("1", "HALLUCINATED", "HALLUCINATED")]
        b = [make_row("2", "HALLUCINATED", "HALLUCINATED")]

        with self.assertRaises(ValueError):
            mcnemar_test(a, b)

    def test_mismatched_ground_truth(self):
        a = [make_row("1", "HALLUCINATED", "HALLUCINATED")]
        b = [make_row("1", "UNVERIFIED", "UNVERIFIED")]

        with self.assertRaises(ValueError):
            mcnemar_test(a, b)

    def test_duplicate_completed_ids(self):
        a = [
            make_row("1", "HALLUCINATED", "HALLUCINATED"),
            make_row("1", "HALLUCINATED", "HALLUCINATED"),
        ]
        b = [make_row("1", "HALLUCINATED", "HALLUCINATED")]

        with self.assertRaises(ValueError):
            mcnemar_test(a, b)


if __name__ == "__main__":
    unittest.main()
