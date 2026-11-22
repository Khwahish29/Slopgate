"""Read-only review viewer for SlopGate D3/D4 robustness evaluations."""

import argparse
import json
from collections import Counter
from pathlib import Path


def load_jsonl(path):
    path = Path(path)
    rows = []

    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "{}:{}: invalid JSON: {}".format(path, number, exc)
                ) from exc

            if not isinstance(row, dict) or not row.get("id"):
                raise ValueError(
                    "{}:{}: missing report id".format(path, number)
                )
            rows.append(row)

    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate report IDs in {}".format(path))

    return rows


def dataset_kind(row):
    identifier = str(row.get("id", "")).lower()

    if identifier.startswith("d3-"):
        return "D3"
    if identifier.startswith("d4-"):
        return "D4"

    tier = str(row.get("tier", "")).upper()
    if tier in ("D3", "D4"):
        return tier

    return "OTHER"


def join_predictions(dataset, predictions):
    indexed = {row["id"]: row for row in predictions}
    output = []

    for item in dataset:
        prediction = indexed.get(item["id"])
        row = dict(item)

        if prediction is None:
            row["prediction_status"] = "missing"
            row["predicted_verdict"] = None
            row["correct"] = None
            row["prediction"] = None
        else:
            verdict = prediction.get("verdict")
            status = prediction.get("status", "ok")

            row["prediction_status"] = status
            row["predicted_verdict"] = verdict
            row["correct"] = (
                verdict == item.get("expected_verdict")
                if status == "ok"
                else None
            )
            row["prediction"] = prediction

        output.append(row)

    return output


def summarize(rows):
    summary = {
        "total": len(rows),
        "by_dataset": {},
        "by_subtype": {},
        "by_injection_direction": {},
        "prediction_status": {},
        "completed": 0,
        "correct": 0,
        "incorrect": 0,
        "missing": 0,
        "accuracy": None,
    }

    dataset_counts = Counter()
    subtype_counts = Counter()
    direction_counts = Counter()
    status_counts = Counter()

    for row in rows:
        dataset_counts[dataset_kind(row)] += 1
        subtype_counts[str(row.get("subtype", "unknown"))] += 1

        injection = row.get("injection")
        if isinstance(injection, dict):
            direction_counts[str(injection.get("direction", "unknown"))] += 1

        status = row.get("prediction_status", "missing")
        status_counts[status] += 1

        if status == "missing":
            summary["missing"] += 1

        if row.get("correct") is True:
            summary["correct"] += 1
            summary["completed"] += 1
        elif row.get("correct") is False:
            summary["incorrect"] += 1
            summary["completed"] += 1

    summary["by_dataset"] = dict(sorted(dataset_counts.items()))
    summary["by_subtype"] = dict(sorted(subtype_counts.items()))
    summary["by_injection_direction"] = dict(sorted(direction_counts.items()))
    summary["prediction_status"] = dict(sorted(status_counts.items()))

    if summary["completed"]:
        summary["accuracy"] = (
            summary["correct"] / summary["completed"]
        )

    return summary


def filter_rows(rows, dataset=None, subtype=None, errors_only=False):
    selected = []

    for row in rows:
        if dataset and dataset_kind(row) != dataset.upper():
            continue
        if subtype and row.get("subtype") != subtype:
            continue
        if errors_only and row.get("correct") is not False:
            continue
        selected.append(row)

    return selected


def display_report(row, show_report=False):
    injection = row.get("injection") or {}
    prediction = row.get("prediction") or {}

    print("=" * 72)
    print("ID:", row.get("id"))
    print("Dataset:", dataset_kind(row))
    print("Base report:", row.get("base_id"))
    print("Repository:", row.get("repo"))
    print("Subtype:", row.get("subtype"))
    print("Gold:", row.get("gold"))
    print("Expected:", row.get("expected_verdict"))
    print("Predicted:", row.get("predicted_verdict"))
    print("Status:", row.get("prediction_status"))
    print("Correct:", row.get("correct"))

    if injection:
        print("Injection kind:", injection.get("kind"))
        print("Injection direction:", injection.get("direction"))
        print("Injection text:", injection.get("text"))

    print("Truth:", row.get("truth"))

    if prediction:
        print("Rationale:", prediction.get("rationale"))
        print("Tool calls:", prediction.get("tool_calls"))
        print("Model calls:", prediction.get("model_calls"))
        print("Tokens:", prediction.get("tokens"))

        for field in ("ledger", "trace"):
            value = prediction.get(field)
            if value:
                print("{}:".format(field))
                print(json.dumps(value, indent=2, default=str))

    if show_report:
        print("\nREPORT:")
        print(row.get("report", ""))

    print()


def review(
    data_path,
    predictions_path=None,
    dataset=None,
    subtype=None,
    errors_only=False,
    show_report=False,
    limit=None,
    export=None,
):
    dataset_rows = load_jsonl(data_path)

    predictions = (
        load_jsonl(predictions_path)
        if predictions_path
        else []
    )

    rows = join_predictions(dataset_rows, predictions)

    rows = filter_rows(
        rows,
        dataset=dataset,
        subtype=subtype,
        errors_only=errors_only,
    )

    summary = summarize(rows)

    print("\n===== REVIEW SUMMARY =====")
    print(json.dumps(summary, indent=2))

    displayed = rows if limit is None else rows[:limit]

    for row in displayed:
        display_report(row, show_report=show_report)

    if export:
        path = Path(export)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "summary": summary,
            "reports": rows,
        }

        path.write_text(
            json.dumps(payload, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

        print("Exported review:", path)

    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Review D3/D4 robustness reports and predictions"
    )

    parser.add_argument("--data", required=True)
    parser.add_argument("--predictions")
    parser.add_argument("--dataset", choices=["D3", "D4"])
    parser.add_argument("--subtype")
    parser.add_argument("--errors-only", action="store_true")
    parser.add_argument("--show-report", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--export")

    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be nonnegative")

    review(
        data_path=args.data,
        predictions_path=args.predictions,
        dataset=args.dataset,
        subtype=args.subtype,
        errors_only=args.errors_only,
        show_report=args.show_report,
        limit=args.limit,
        export=args.export,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
