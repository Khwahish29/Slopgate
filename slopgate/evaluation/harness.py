
"""Run SlopGate systems against labeled JSONL datasets.

Usage:
    python -m slopgate.evaluation.harness \
        --data corpus/d1/d1.jsonl \
        --systems b1 b3_rules \
        --out results/d1
"""

import argparse
import json
import time
from pathlib import Path

from ..agent_layer.baselines import build
from ..agent_layer.baselines.base import Skipped
from ..agent_layer.tools import Workspace
from ..datasets.d1 import load
from .scoring import expected_label, score_predictions


VALID_VERDICTS = (
    "HALLUCINATED",
    "UNVERIFIED",
    "REPRODUCIBLE",
)


def make_result_row(item, system_name):
    """Create a consistent result record for each report."""
    return {
        "id": item["id"],
        "system": system_name,
        "tier": item.get("tier"),
        "repo": item["repo"],
        "gold": item["gold"],
        "expected_verdict": expected_label(item),
        "verdict": None,
        "status": "error",
        "confidence": None,
        "tool_calls": None,
        "tokens": None,
        "model_calls": None,
        "latency_s": None,
        "ledger": None,
        "trace": None,
        "rationale": None,
        "error": None,
    }


def evaluate(items, system_name, limit=None):
    """Evaluate a system while reusing and cleaning workspaces."""
    items = list(items)

    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        items = items[:limit]

    rows = []
    workspaces = {}

    try:
        system = build(system_name)
    except Skipped as exc:
        for item in items:
            row = make_result_row(item, system_name)
            row["status"] = "skipped"
            row["error"] = str(exc)
            rows.append(row)
        return rows

    try:
        for item in items:
            row = make_result_row(item, system_name)
            started = time.perf_counter()

            try:
                repo = item["repo"]
                report_path = item.get("report_path")

                if not report_path:
                    raise ValueError(
                        f"Missing report_path for {item['id']}"
                    )

                if not Path(report_path).is_file():
                    raise FileNotFoundError(report_path)

                if not Path(repo).is_dir():
                    raise FileNotFoundError(repo)

                if repo not in workspaces:
                    workspaces[repo] = Workspace(repo)

                result = system.triage(
                    report_path,
                    workspaces[repo],
                    repo,
                )

                if not isinstance(result, dict):
                    raise ValueError(
                        "System must return a dictionary"
                    )

                verdict = result.get("verdict")
                if verdict not in VALID_VERDICTS:
                    raise ValueError(
                        f"Invalid verdict: {verdict!r}"
                    )

                row.update({
                    "status": "ok",
                    "verdict": verdict,
                    "confidence": result.get("confidence"),
                    "tool_calls": result.get("tool_calls"),
                    "tokens": result.get("tokens"),
                    "model_calls": result.get("model_calls"),
                    "latency_s": result.get(
                        "latency_s",
                        time.perf_counter() - started,
                    ),
                    "ledger": result.get("ledger"),
                    "trace": result.get("trace"),
                    "rationale": result.get("rationale"),
                })

            except Skipped as exc:
                row.update({
                    "status": "skipped",
                    "error": str(exc),
                    "latency_s": time.perf_counter() - started,
                })

            except Exception as exc:
                row.update({
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "latency_s": time.perf_counter() - started,
                })

            rows.append(row)

    finally:
        for workspace in workspaces.values():
            workspace.close()

    return rows


def save_results(rows, output_dir, system_name):
    """Write predictions and aggregate metrics."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    predictions_file = output / f"{system_name}_predictions.jsonl"
    metrics_file = output / f"{system_name}_metrics.json"

    with predictions_file.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")

    metrics = score_predictions(rows)

    with metrics_file.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
        f.write("\n")

    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="SlopGate evaluation harness"
    )

    parser.add_argument(
        "--data",
        default="corpus/d1/d1.jsonl",
    )
    parser.add_argument(
        "--systems",
        nargs="+",
        default=["b1", "b3_rules"],
    )
    parser.add_argument(
        "--out",
        default="results/d1",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be non-negative")

    items = load(args.data)

    print(f"Loaded {len(items)} dataset reports")

    for system_name in args.systems:
        print(f"\nEvaluating {system_name}...")

        rows = evaluate(
            items,
            system_name,
            limit=args.limit,
        )

        metrics = save_results(
            rows,
            args.out,
            system_name,
        )

        print(
            f"Completed: {metrics['completed']}"
            f"/{metrics['total']}"
        )
        print(f"Accuracy: {metrics['accuracy']}")
        print(f"Coverage: {metrics['coverage']}")
        print(f"Errors: {metrics['errors']}")
        print(f"Skipped: {metrics['skipped']}")

        if metrics["false_hallucination_rate"] is not None:
            print(
                "False-hallucination rate: "
                f"{metrics['false_hallucination_rate']:.2%}"
            )

        if metrics["hallucination_recall"] is not None:
            print(
                "Hallucination recall: "
                f"{metrics['hallucination_recall']:.2%}"
            )

        print(
            "Mean classification cost: "
            f"{metrics['mean_classification_cost']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
