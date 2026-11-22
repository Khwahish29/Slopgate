"""Resumable evaluation runner for SlopGate.

Runs one report at a time, checkpoints after every report, and
reuses successful results when resumed with the same dataset.

Usage:
    python -m slopgate.evaluation.resume \
        --data corpus/d1/d1.jsonl \
        --systems b1 \
        --out results/resumable
"""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from ..datasets.d1 import load
from .harness import evaluate
from .scoring import score_predictions


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)

    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, default=str) + "\n")

            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)

    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def dataset_fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_resumable(
    items,
    system_name,
    output_dir,
    fingerprint,
    retry_errors=True,
):
    items = list(items)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    predictions_path = output / (
        system_name + "_predictions.jsonl"
    )
    metrics_path = output / (
        system_name + "_metrics.json"
    )
    metadata_path = output / (
        system_name + "_run.json"
    )

    metadata = {
        "system": system_name,
        "dataset_sha256": fingerprint,
        "report_count": len(items),
        "report_ids": [item["id"] for item in items],
    }

    if len(set(metadata["report_ids"])) != len(items):
        raise ValueError("Dataset contains duplicate report IDs")

    if metadata_path.exists():
        existing_metadata = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )

        if existing_metadata != metadata:
            raise ValueError(
                "Existing run metadata differs. "
                "Use a different output directory."
            )

    elif predictions_path.exists():
        raise ValueError(
            "Predictions exist without run metadata. "
            "Use a different output directory."
        )

    else:
        atomic_json(metadata_path, metadata)

    previous = {}

    if predictions_path.exists():
        with predictions_path.open(
            "r", encoding="utf-8"
        ) as handle:
            for line in handle:
                if not line.strip():
                    continue

                row = json.loads(line)
                report_id = row["id"]

                if report_id in previous:
                    raise ValueError(
                        "Duplicate saved report ID: " + report_id
                    )

                previous[report_id] = row

    allowed_ids = set(metadata["report_ids"])

    if not set(previous).issubset(allowed_ids):
        raise ValueError(
            "Saved predictions contain unknown report IDs"
        )

    for item in items:
        report_id = item["id"]
        existing = previous.get(report_id)

        if existing is not None:
            if existing.get("system") != system_name:
                raise ValueError(
                    "Saved prediction has a different system"
                )

            if existing.get("expected_verdict") != (
                item.get("expected_verdict")
                or (
                    "HALLUCINATED"
                    if item["gold"] == "HALLUCINATED"
                    else "UNVERIFIED"
                )
            ):
                raise ValueError(
                    "Saved prediction has inconsistent ground truth"
                )

            if existing.get("status") == "ok":
                print("REUSED:", report_id)
                continue

            if not retry_errors:
                print("PRESERVED:", report_id)
                continue

        print("RUNNING:", report_id)

        result = evaluate([item], system_name)[0]
        previous[report_id] = result

        ordered = [
            previous[current["id"]]
            for current in items
            if current["id"] in previous
        ]

        atomic_jsonl(predictions_path, ordered)
        atomic_json(metrics_path, score_predictions(ordered))

    rows = [
        previous[item["id"]]
        for item in items
        if item["id"] in previous
    ]

    metrics = score_predictions(rows)
    atomic_json(metrics_path, metrics)

    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Resumable SlopGate evaluation"
    )

    parser.add_argument(
        "--data",
        default="corpus/d1/d1.jsonl",
    )
    parser.add_argument(
        "--systems",
        nargs="+",
        default=["b1"],
    )
    parser.add_argument(
        "--out",
        default="results/resumable",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--no-retry-errors",
        action="store_true",
    )

    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be non-negative")

    items = load(args.data)

    if args.limit is not None:
        items = items[:args.limit]

    fingerprint = dataset_fingerprint(args.data)

    for system_name in args.systems:
        print("\nSYSTEM:", system_name)

        metrics = run_resumable(
            items,
            system_name,
            args.out,
            fingerprint,
            retry_errors=not args.no_retry_errors,
        )

        print(
            "Completed:",
            metrics["completed"],
            "/",
            metrics["total"],
        )
        print("Accuracy:", metrics["accuracy"])
        print("Coverage:", metrics["coverage"])
        print("Errors:", metrics["errors"])
        print("Skipped:", metrics["skipped"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
