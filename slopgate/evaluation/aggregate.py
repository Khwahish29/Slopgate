"""Aggregate comparable SlopGate evaluation runs."""

import argparse
import csv
import json
from pathlib import Path

from .scoring import score_predictions


FIELDS = [
    "system", "total", "completed", "coverage",
    "accuracy", "macro_f1", "false_hallucinated",
    "false_hallucination_rate", "hallucination_precision",
    "hallucination_recall", "classification_cost",
    "mean_classification_cost", "mean_tool_calls",
    "mean_tokens", "mean_latency_s", "errors", "skipped",
]


def load_predictions(path):
    rows = []
    seen = set()

    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue

            row = json.loads(line)
            report_id = row["id"]

            if report_id in seen:
                raise ValueError(
                    "Duplicate report ID in {}: {}".format(
                        path, report_id
                    )
                )

            seen.add(report_id)
            rows.append(row)

    return rows


def aggregate(input_dir, output_dir):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    files = sorted(input_dir.glob("*_predictions.jsonl"))

    if not files:
        raise ValueError("No prediction files found")

    summary = []
    reference_ids = None
    reference_fingerprint = None
    reference_count = None
    metadata_present = None

    for path in files:
        system = path.name[:-len("_predictions.jsonl")]
        rows = load_predictions(path)
        ids = {row["id"] for row in rows}

        for row in rows:
            if row.get("system") != system:
                raise ValueError(
                    "System mismatch in {}".format(path)
                )

        if reference_ids is None:
            reference_ids = ids
        elif ids != reference_ids:
            raise ValueError(
                "Systems have different report ID sets"
            )

        metadata_path = input_dir / (
            system + "_run.json"
        )
        has_metadata = metadata_path.exists()

        if metadata_present is None:
            metadata_present = has_metadata
        elif has_metadata != metadata_present:
            raise ValueError(
                "Cannot mix runs with and without metadata"
            )

        if has_metadata:
            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )

            if metadata.get("system") != system:
                raise ValueError("Run metadata system mismatch")

            fingerprint = metadata.get("dataset_sha256")
            report_ids = metadata.get("report_ids")
            count = metadata.get("report_count")

            if not isinstance(fingerprint, str) or not fingerprint:
                raise ValueError("Missing dataset fingerprint")

            if not isinstance(report_ids, list):
                raise ValueError("Missing metadata report IDs")

            if len(report_ids) != len(set(report_ids)):
                raise ValueError("Duplicate metadata report IDs")

            if count != len(report_ids):
                raise ValueError("Invalid metadata report count")

            if not ids.issubset(set(report_ids)):
                raise ValueError(
                    "Predictions are not part of the recorded run"
                )

            if reference_fingerprint is None:
                reference_fingerprint = fingerprint
                reference_count = count
            elif (
                fingerprint != reference_fingerprint
                or count != reference_count
            ):
                raise ValueError(
                    "Systems use different datasets"
                )

        metrics = score_predictions(rows)
        record = {"system": system}
        record.update(metrics)
        summary.append(record)

    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "comparison.json"
    csv_path = output_dir / "comparison.csv"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    with csv_path.open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(summary)

    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Aggregate SlopGate evaluation results"
    )
    parser.add_argument("--input", default="results/resumable")
    parser.add_argument("--out", default="results/summary")
    args = parser.parse_args(argv)

    summary = aggregate(args.input, args.out)

    print("Aggregated {} systems".format(len(summary)))
    for record in summary:
        print(
            "{}: accuracy={}, coverage={}, cost={}".format(
                record["system"],
                record["accuracy"],
                record["coverage"],
                record["mean_classification_cost"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
