"""Run and compare registered SlopGate agent ablations."""

import argparse
import json
from pathlib import Path

from slopgate.agent_layer.baselines.base import REGISTRY
from slopgate.evaluation.aggregate import aggregate
from slopgate.evaluation.resume import (
    dataset_fingerprint,
    run_resumable,
)
from slopgate.datasets.d1 import load


ABLATIONS = (
    "agent_no_skeptic",
    "agent_same_model_skeptic",
    "agent_no_citation",
    "agent_no_history",
)


def register_systems():
    """Import modules that register agent variants."""
    import slopgate.agent_layer.agent_ablations  # noqa: F401


def run_ablations(
    data_path,
    output_dir,
    systems=None,
    limit=None,
    retry_errors=True,
):
    register_systems()

    systems = list(ABLATIONS if systems is None else systems)

    if not systems:
        raise ValueError("At least one system is required")

    if len(systems) != len(set(systems)):
        raise ValueError("Duplicate system names")

    for name in systems:
        if name not in ABLATIONS:
            raise ValueError("Not a registered ablation: " + name)
        if name not in REGISTRY:
            raise ValueError("Ablation is missing from registry: " + name)

    data_path = Path(data_path)
    output_dir = Path(output_dir)

    items = load(str(data_path))

    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        items = items[:limit]

    if not items:
        raise ValueError("No reports to evaluate")

    fingerprint = dataset_fingerprint(data_path)

    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    for name in systems:
        print("\n===== RUNNING {} =====".format(name), flush=True)

        metrics = run_resumable(
            items,
            name,
            output_dir,
            fingerprint,
            retry_errors=retry_errors,
        )

        results[name] = metrics

        print(
            "{}: completed={}, accuracy={}, errors={}, skipped={}".format(
                name,
                metrics["completed"],
                metrics["accuracy"],
                metrics["errors"],
                metrics["skipped"],
            ),
            flush=True,
        )

    # Only compare systems when all requested runs have
    # produced predictions for the same report IDs.
    if len(systems) > 1:
        comparison_dir = output_dir / "comparison"
        aggregate(output_dir, comparison_dir)

    summary_path = output_dir / "ablation_summary.json"

    summary_path.write_text(
        json.dumps(results, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\nSaved:", summary_path)

    return results


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run registered SlopGate agent ablations"
    )

    parser.add_argument(
        "--data",
        default="corpus/d1/d1.jsonl",
    )
    parser.add_argument(
        "--out",
        default="results/ablations",
    )
    parser.add_argument(
        "--systems",
        nargs="+",
        choices=ABLATIONS,
        default=list(ABLATIONS),
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--no-retry-errors",
        action="store_true",
    )

    args = parser.parse_args(argv)

    run_ablations(
        data_path=args.data,
        output_dir=args.out,
        systems=args.systems,
        limit=args.limit,
        retry_errors=not args.no_retry_errors,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
