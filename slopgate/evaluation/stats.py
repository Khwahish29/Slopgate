"""Statistical analysis for paired SlopGate evaluations."""

import argparse
import json
import math
import random
from pathlib import Path

from .aggregate import load_predictions
from .scoring import score_predictions


def bootstrap_ci(rows, metric="accuracy", confidence=0.95,
                 samples=2000, seed=42):
    """Percentile bootstrap confidence interval over completed reports."""
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if samples < 1:
        raise ValueError("samples must be positive")

    completed = [r for r in rows if r.get("status") == "ok"]

    if not completed:
        return {"estimate": None, "lower": None, "upper": None,
                "confidence": confidence, "n": 0}

    estimate = score_predictions(completed).get(metric)
    if estimate is None:
        return {"estimate": None, "lower": None, "upper": None,
                "confidence": confidence, "n": len(completed)}

    rng = random.Random(seed)
    n = len(completed)
    values = []

    for _ in range(samples):
        sample = [completed[rng.randrange(n)] for _ in range(n)]
        value = score_predictions(sample).get(metric)
        if value is not None and math.isfinite(value):
            values.append(value)

    if not values:
        lower = upper = None
    else:
        values.sort()
        alpha = (1 - confidence) / 2
        lower = values[max(0, int(alpha * len(values)))]
        upper = values[min(
            len(values) - 1,
            int((1 - alpha) * len(values))
        )]

    return {
        "estimate": estimate,
        "lower": lower,
        "upper": upper,
        "confidence": confidence,
        "n": n,
        "bootstrap_samples": len(values),
    }


def mcnemar_test(rows_a, rows_b):
    """Exact two-sided McNemar test on paired completed predictions."""
    a = {
        r["id"]: r for r in rows_a
        if r.get("status") == "ok"
    }
    b = {
        r["id"]: r for r in rows_b
        if r.get("status") == "ok"
    }

    if len(a) != len([
        r for r in rows_a if r.get("status") == "ok"
    ]):
        raise ValueError("Duplicate completed IDs in system A")

    if len(b) != len([
        r for r in rows_b if r.get("status") == "ok"
    ]):
        raise ValueError("Duplicate completed IDs in system B")

    if set(a) != set(b):
        raise ValueError("Systems must have matching completed report IDs")

    a_only = 0
    b_only = 0
    both_correct = 0
    both_wrong = 0

    for report_id in a:
        ra = a[report_id]
        rb = b[report_id]

        if ra["expected_verdict"] != rb["expected_verdict"]:
            raise ValueError("Ground-truth mismatch")

        correct_a = ra["verdict"] == ra["expected_verdict"]
        correct_b = rb["verdict"] == rb["expected_verdict"]

        if correct_a and correct_b:
            both_correct += 1
        elif correct_a:
            a_only += 1
        elif correct_b:
            b_only += 1
        else:
            both_wrong += 1

    discordant = a_only + b_only

    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(
            math.comb(discordant, k)
            for k in range(min(a_only, b_only) + 1)
        ) / (2 ** discordant)
        p_value = min(1.0, 2 * tail)

    return {
        "n": len(a),
        "both_correct": both_correct,
        "a_only_correct": a_only,
        "b_only_correct": b_only,
        "both_wrong": both_wrong,
        "discordant": discordant,
        "p_value": p_value,
        "significant_0_05": p_value < 0.05,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="SlopGate statistical comparison"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--system-a", required=True)
    parser.add_argument("--system-b", required=True)
    parser.add_argument("--out", default="results/statistics.json")
    parser.add_argument("--samples", type=int, default=2000)
    args = parser.parse_args(argv)

    directory = Path(args.input)

    rows_a = load_predictions(
        directory / (args.system_a + "_predictions.jsonl")
    )
    rows_b = load_predictions(
        directory / (args.system_b + "_predictions.jsonl")
    )

    result = {
        "system_a": args.system_a,
        "system_b": args.system_b,
        "bootstrap": {
            args.system_a: {
                metric: bootstrap_ci(rows_a, metric, samples=args.samples)
                for metric in (
                    "accuracy",
                    "hallucination_recall",
                    "mean_classification_cost",
                )
            },
            args.system_b: {
                metric: bootstrap_ci(rows_b, metric, samples=args.samples)
                for metric in (
                    "accuracy",
                    "hallucination_recall",
                    "mean_classification_cost",
                )
            },
        },
        "mcnemar": mcnemar_test(rows_a, rows_b),
    }

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )

    print("McNemar p-value:", result["mcnemar"]["p_value"])
    print("Significant at 0.05:",
          result["mcnemar"]["significant_0_05"])
    print("Saved:", output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
