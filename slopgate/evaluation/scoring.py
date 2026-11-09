
"""Evaluation metrics for SlopGate benchmark predictions."""

from collections import Counter

LABELS = ("HALLUCINATED", "UNVERIFIED", "REPRODUCIBLE")


def expected_label(item):
    """Map dataset ground truth to the expected system verdict."""
    if "expected_verdict" in item:
        label = item["expected_verdict"]
    else:
        gold = item["gold"]
        mapping = {
            "HALLUCINATED": "HALLUCINATED",
            "NOT_HALLUCINATED": "UNVERIFIED",
        }
        if gold not in mapping:
            raise ValueError(f"Unknown gold label: {gold}")
        label = mapping[gold]

    if label not in LABELS:
        raise ValueError(f"Unknown expected verdict: {label}")
    return label


def score_predictions(rows):
    """Score per-report results from the evaluation harness.

    Each row must contain:
        expected_verdict, verdict, status

    Only status='ok' rows are scored.
    Skipped and errored rows are tracked separately.
    """
    rows = list(rows)
    completed = [r for r in rows if r.get("status") == "ok"]

    for row in completed:
        if row.get("expected_verdict") not in LABELS:
            raise ValueError("Invalid expected verdict")
        if row.get("verdict") not in LABELS:
            raise ValueError("Invalid predicted verdict")

    total = len(rows)
    correct = sum(
        r["verdict"] == r["expected_verdict"]
        for r in completed
    )

    confusion = {
        expected: {predicted: 0 for predicted in LABELS}
        for expected in LABELS
    }

    for row in completed:
        confusion[row["expected_verdict"]][row["verdict"]] += 1

    per_class = {}

    for label in LABELS:
        tp = confusion[label][label]
        fp = sum(
            confusion[other][label]
            for other in LABELS if other != label
        )
        fn = sum(
            confusion[label][other]
            for other in LABELS if other != label
        )

        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall else 0.0
        )

        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": tp + fn,
        }

    status_counts = Counter(r.get("status", "unknown") for r in rows)

    def mean(field):
        values = [
            r[field] for r in completed
            if isinstance(r.get(field), (int, float))
            and not isinstance(r[field], bool)
        ]
        return sum(values) / len(values) if values else None

    return {
        "total": total,
        "completed": len(completed),
        "skipped": status_counts["skipped"],
        "errors": status_counts["error"],
        "accuracy": correct / len(completed) if completed else None,
        "coverage": len(completed) / total if total else None,
        "correct": correct,
        "confusion_matrix": confusion,
        "per_class": per_class,
        "macro_f1": (
            sum(m["f1"] for m in per_class.values()) / len(LABELS)
            if completed else None
        ),
        "mean_tool_calls": mean("tool_calls"),
        "mean_tokens": mean("tokens"),
        "mean_latency_s": mean("latency_s"),
    }
