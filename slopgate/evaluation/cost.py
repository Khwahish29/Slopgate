"""Cost accounting for SlopGate evaluation predictions.

API charges are reported only when recorded or when a price is
explicitly supplied. Classification penalties are separate from USD.
"""

import argparse
import csv
import json
import math
from pathlib import Path

from .aggregate import load_predictions
from .scoring import score_predictions


def nonnegative_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("{} must be a number".format(name))
    if not math.isfinite(value) or value < 0:
        raise ValueError("{} must be finite and nonnegative".format(name))
    return float(value)


def optional_number(value, name):
    if value is None:
        return None
    return nonnegative_number(value, name)


def account_system(rows, system, usd_per_1k_tokens=None):
    """Summarize costs and usage for one system."""
    if usd_per_1k_tokens is not None:
        usd_per_1k_tokens = nonnegative_number(
            usd_per_1k_tokens, "usd_per_1k_tokens"
        )

    metrics = score_predictions(rows)
    completed = [r for r in rows if r.get("status") == "ok"]

    total_tokens = 0.0
    total_model_calls = 0.0
    total_tool_calls = 0.0
    total_latency = 0.0

    missing_tokens = 0
    missing_model_calls = 0
    missing_tool_calls = 0
    missing_latency = 0

    api_cost_usd = 0.0
    priced_reports = 0
    unpriced_reports = 0
    recorded_reports = 0
    estimated_reports = 0

    for row in completed:
        tokens = optional_number(row.get("tokens"), "tokens")
        calls = optional_number(row.get("model_calls"), "model_calls")
        tools = optional_number(row.get("tool_calls"), "tool_calls")
        latency = optional_number(row.get("latency_s"), "latency_s")
        recorded_cost = optional_number(
            row.get("cost_usd"), "cost_usd"
        )

        if tokens is None:
            missing_tokens += 1
        else:
            total_tokens += tokens

        if calls is None:
            missing_model_calls += 1
        else:
            total_model_calls += calls

        if tools is None:
            missing_tool_calls += 1
        else:
            total_tool_calls += tools

        if latency is None:
            missing_latency += 1
        else:
            total_latency += latency

        if recorded_cost is not None:
            api_cost_usd += recorded_cost
            priced_reports += 1
            recorded_reports += 1
        elif calls == 0:
            # No model calls: no model API charge.
            priced_reports += 1
        elif tokens is not None and usd_per_1k_tokens is not None:
            api_cost_usd += tokens / 1000.0 * usd_per_1k_tokens
            priced_reports += 1
            estimated_reports += 1
        else:
            unpriced_reports += 1

    count = len(completed)
    fully_priced = unpriced_reports == 0

    return {
        "system": system,
        "total_reports": metrics["total"],
        "completed_reports": count,
        "errors": metrics["errors"],
        "skipped": metrics["skipped"],
        "total_tokens": total_tokens if not missing_tokens else None,
        "total_model_calls": (
            total_model_calls if not missing_model_calls else None
        ),
        "total_tool_calls": (
            total_tool_calls if not missing_tool_calls else None
        ),
        "total_latency_s": (
            total_latency if not missing_latency else None
        ),
        "mean_latency_s": (
            total_latency / count
            if count and not missing_latency else None
        ),
        "api_cost_usd": (
            round(api_cost_usd, 8) if fully_priced else None
        ),
        "known_api_cost_usd": round(api_cost_usd, 8),
        "priced_reports": priced_reports,
        "unpriced_reports": unpriced_reports,
        "recorded_cost_reports": recorded_reports,
        "estimated_cost_reports": estimated_reports,
        "pricing_complete": fully_priced,
        "usd_per_1k_tokens_assumption": usd_per_1k_tokens,
        "classification_cost_units": metrics["classification_cost"],
        "mean_classification_cost_units": (
            metrics["mean_classification_cost"]
        ),
        "false_dismissals": metrics["false_hallucinated"],
        "missed_hallucinations": metrics["missed_hallucinated"],
    }


def account_directory(input_dir, output_dir, usd_per_1k_tokens=None):
    """Write JSON and CSV summaries for all prediction files."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    paths = sorted(input_dir.glob("*_predictions.jsonl"))
    if not paths:
        raise ValueError("No prediction files found")

    summaries = []

    for path in paths:
        system = path.name[:-len("_predictions.jsonl")]
        rows = load_predictions(path)

        if any(row.get("system") != system for row in rows):
            raise ValueError("System mismatch in {}".format(path))

        summaries.append(
            account_system(rows, system, usd_per_1k_tokens)
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "cost_summary.json"
    csv_path = output_dir / "cost_summary.csv"

    json_path.write_text(
        json.dumps(summaries, indent=2) + "\n",
        encoding="utf-8",
    )

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(summaries[0].keys())
        )
        writer.writeheader()
        writer.writerows(summaries)

    return summaries


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="SlopGate evaluation cost accounting"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", default="results/summary")
    parser.add_argument(
        "--usd-per-1k-tokens",
        type=float,
        default=None,
        help="Explicit flat token-price assumption in USD",
    )

    args = parser.parse_args(argv)

    summaries = account_directory(
        args.input,
        args.out,
        args.usd_per_1k_tokens,
    )

    for summary in summaries:
        print(
            "{}: model_calls={}, tokens={}, api_cost_usd={}, "
            "classification_cost={}".format(
                summary["system"],
                summary["total_model_calls"],
                summary["total_tokens"],
                summary["api_cost_usd"],
                summary["classification_cost_units"],
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
