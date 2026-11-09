
"""Evaluation metrics for SlopGate benchmark predictions."""

from collections import Counter, defaultdict
from math import isfinite


LABELS = ("HALLUCINATED", "UNVERIFIED", "REPRODUCIBLE")

FALSE_DISMISSAL_COST = 500
MISSED_HALLUCINATION_COST = 1


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


def safe_divide(numerator, denominator):
    """Return None when a rate has no denominator."""
    return numerator / denominator if denominator else None


def calculate_mean(rows, field):
    """Average finite numeric values from completed rows."""
    values = []

    for row in rows:
        value = row.get(field)

        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isfinite(value)
        ):
            values.append(value)

    return sum(values) / len(values) if values else None


def calculate_group_accuracy(rows, field):
    """Calculate accuracy for each tier or repository."""
    groups = defaultdict(list)

    for row in rows:
        group = row.get(field)

        if group is not None:
            groups[str(group)].append(row)

    results = {}

    for group, group_rows in sorted(groups.items()):
        total = len(group_rows)
        correct = sum(
            row["verdict"] == row["expected_verdict"]
            for row in group_rows
        )

        results[group] = {
            "total": total,
            "correct": correct,
            "incorrect": total - correct,
            "accuracy": safe_divide(correct, total),
        }

    return results


def score_predictions(rows):
    """Score evaluation results and calculate benchmark metrics.

    Only status='ok' rows are scored.

    Hallucination metrics:
        False hallucination:
            A real report predicted HALLUCINATED.

        Missed hallucination:
            A hallucinated report predicted as something else.

    Classification cost:
        500 * false hallucinations + 1 * missed hallucinations.

    This is a simplified classification-cost diagnostic,
    not the complete stakeholder cost model.
    """
    rows = list(rows)

    completed = [
        row for row in rows
        if row.get("status") == "ok"
    ]

    for row in completed:
        if row.get("expected_verdict") not in LABELS:
            raise ValueError("Invalid expected verdict")

        if row.get("verdict") not in LABELS:
            raise ValueError("Invalid predicted verdict")

    total = len(rows)
    completed_count = len(completed)

    status_counts = Counter(
        row.get("status", "unknown")
        for row in rows
    )

    correct = sum(
        row["verdict"] == row["expected_verdict"]
        for row in completed
    )

    # -----------------------------------------
    # Confusion matrix
    # -----------------------------------------

    confusion = {
        expected: {
            predicted: 0
            for predicted in LABELS
        }
        for expected in LABELS
    }

    for row in completed:
        expected = row["expected_verdict"]
        predicted = row["verdict"]
        confusion[expected][predicted] += 1

    # -----------------------------------------
    # Per-class metrics
    # -----------------------------------------

    per_class = {}

    for label in LABELS:
        tp = confusion[label][label]

        fp = sum(
            confusion[other][label]
            for other in LABELS
            if other != label
        )

        fn = sum(
            confusion[label][other]
            for other in LABELS
            if other != label
        )

        precision = (
            tp / (tp + fp)
            if tp + fp else 0.0
        )

        recall = (
            tp / (tp + fn)
            if tp + fn else 0.0
        )

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

    # Macro F1 over classes represented in ground truth.
    supported_classes = [
        metrics["f1"]
        for metrics in per_class.values()
        if metrics["support"] > 0
    ]

    macro_f1 = (
        sum(supported_classes) / len(supported_classes)
        if supported_classes else None
    )

    # -----------------------------------------
    # Hallucination-specific metrics
    # -----------------------------------------

    real_reports = [
        row for row in completed
        if row["expected_verdict"] in (
            "UNVERIFIED",
            "REPRODUCIBLE",
        )
    ]

    hallucinated_reports = [
        row for row in completed
        if row["expected_verdict"] == "HALLUCINATED"
    ]

    false_hallucinated = sum(
        row["verdict"] == "HALLUCINATED"
        for row in real_reports
    )

    missed_hallucinated = sum(
        row["verdict"] != "HALLUCINATED"
        for row in hallucinated_reports
    )

    true_hallucinated = (
        len(hallucinated_reports) - missed_hallucinated
    )

    false_hallucination_rate = safe_divide(
        false_hallucinated,
        len(real_reports),
    )

    hallucination_recall = safe_divide(
        true_hallucinated,
        len(hallucinated_reports),
    )

    hallucination_precision = safe_divide(
        true_hallucinated,
        true_hallucinated + false_hallucinated,
    )

    # -----------------------------------------
    # Classification cost
    # -----------------------------------------

    classification_cost = (
        FALSE_DISMISSAL_COST * false_hallucinated
        + MISSED_HALLUCINATION_COST * missed_hallucinated
    )

    mean_classification_cost = safe_divide(
        classification_cost,
        completed_count,
    )

    # -----------------------------------------
    # Group-level metrics
    # -----------------------------------------

    per_tier = calculate_group_accuracy(
        completed,
        "tier",
    )

    per_repository = calculate_group_accuracy(
        completed,
        "repo",
    )

    # -----------------------------------------
    # Final metrics
    # -----------------------------------------

    return {
        "total": total,
        "completed": completed_count,
        "skipped": status_counts["skipped"],
        "errors": status_counts["error"],
        "correct": correct,

        "accuracy": safe_divide(
            correct,
            completed_count,
        ),

        "coverage": safe_divide(
            completed_count,
            total,
        ),

        "confusion_matrix": confusion,
        "per_class": per_class,
        "macro_f1": macro_f1,

        "real_reports": len(real_reports),
        "hallucinated_reports": len(hallucinated_reports),

        "false_hallucinated": false_hallucinated,
        "false_hallucination_rate": (
            false_hallucination_rate
        ),

        "missed_hallucinated": missed_hallucinated,
        "hallucination_precision": (
            hallucination_precision
        ),
        "hallucination_recall": hallucination_recall,

        "classification_cost": classification_cost,
        "mean_classification_cost": (
            mean_classification_cost
        ),

        "per_tier": per_tier,
        "per_repository": per_repository,

        "mean_tool_calls": calculate_mean(
            completed,
            "tool_calls",
        ),

        "mean_tokens": calculate_mean(
            completed,
            "tokens",
        ),

        "mean_latency_s": calculate_mean(
            completed,
            "latency_s",
        ),
    }
