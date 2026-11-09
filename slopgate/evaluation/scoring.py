
"""Evaluation metrics for SlopGate benchmark predictions.

Metrics:
    - Accuracy and coverage
    - Confusion matrix
    - Per-class precision, recall, F1
    - Macro F1
    - False-hallucination rate
    - Hallucination precision and recall
    - Missed hallucinations
    - Per-tier accuracy
    - Per-repository accuracy
    - Simplified classification cost
    - Average tool calls, tokens, and latency

Only completed rows (status="ok") contribute to prediction metrics.
Skipped and errored rows are counted separately.
"""

from collections import Counter, defaultdict
from math import isfinite

LABELS = (
    "HALLUCINATED",
    "UNVERIFIED",
    "REPRODUCIBLE",
)

FALSE_DISMISSAL_COST = 500
MISSED_HALLUCINATION_COST = 1


def expected_label(item):
    """Map dataset ground truth to the expected system verdict.

    Dataset gold labels:
        HALLUCINATED     -> HALLUCINATED
        NOT_HALLUCINATED -> UNVERIFIED

    An explicit expected_verdict takes precedence.
    """
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
    """Return None when a metric has no valid denominator."""
    return numerator / denominator if denominator else None


def calculate_mean(rows, field):
    """Calculate the mean of finite numeric values for a field."""
    values = [
        row[field]
        for row in rows
        if isinstance(row.get(field), (int, float))
        and not isinstance(row[field], bool)
        and isfinite(row[field])
    ]

    return sum(values) / len(values) if values else None


def calculate_group_accuracy(groups):
    """Calculate accuracy for each tier or repository."""
    output = {}

    for name, group in sorted(groups.items()):
        total = len(group)

        correct = sum(
            row["verdict"] == row["expected_verdict"]
            for row in group
        )

        output[str(name)] = {
            "total": total,
            "correct": correct,
            "incorrect": total - correct,
            "accuracy": safe_divide(correct, total),
        }

    return output


def score_predictions(rows):
    """Calculate evaluation metrics from per-report predictions.

    Required row fields:
        status
        expected_verdict
        verdict

    Optional row fields:
        tier
        repo
        tool_calls
        tokens
        latency_s

    Only rows with status="ok" are scored.

    Classification cost:
        False dismissal of a real report: 500
        Missed hallucinated report: 1

    This is a simplified classification-cost diagnostic,
    not a complete abstention-aware expected-cost model.
    """
    rows = list(rows)

    completed = [
        row for row in rows
        if row.get("status") == "ok"
    ]

    for row in completed:
        if row.get("expected_verdict") not in LABELS:
            raise ValueError(
                f"Invalid expected verdict: "
                f"{row.get('expected_verdict')!r}"
            )

        if row.get("verdict") not in LABELS:
            raise ValueError(
                f"Invalid predicted verdict: "
                f"{row.get('verdict')!r}"
            )

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

    # --------------------------------------------------
    # 1. Confusion matrix
    # --------------------------------------------------

    confusion = {
        actual: {
            predicted: 0
            for predicted in LABELS
        }
        for actual in LABELS
    }

    for row in completed:
        actual = row["expected_verdict"]
        predicted = row["verdict"]

        confusion[actual][predicted] += 1

    # --------------------------------------------------
    # 2. Per-class precision, recall, F1
    # --------------------------------------------------

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

        support = tp + fn

        precision = safe_divide(tp, tp + fp)
        recall = safe_divide(tp, support)

        precision_value = precision if precision is not None else 0.0
        recall_value = recall if recall is not None else 0.0

        f1 = (
            2 * precision_value * recall_value
            / (precision_value + recall_value)
            if precision_value + recall_value
            else 0.0
        )

        per_class[label] = {
            "precision": precision_value,
            "recall": recall_value,
            "f1": f1,
            "support": support,
        }

    # Average only classes represented in ground truth.
    active_classes = [
        metrics
        for metrics in per_class.values()
        if metrics["support"] > 0
    ]

    macro_f1 = (
        sum(metrics["f1"] for metrics in active_classes)
        / len(active_classes)
        if active_classes
        else None
    )

    # --------------------------------------------------
    # 3. Hallucination-specific metrics
    # --------------------------------------------------

    real_reports = sum(
        row["expected_verdict"] == "UNVERIFIED"
        for row in completed
    )

    hallucinated_reports = sum(
        row["expected_verdict"] == "HALLUCINATED"
        for row in completed
    )

    predicted_hallucinated = sum(
        row["verdict"] == "HALLUCINATED"
        for row in completed
    )

    correctly_detected_hallucinated = confusion[
        "HALLUCINATED"
    ]["HALLUCINATED"]

    false_hallucinated = sum(
        row["expected_verdict"] == "UNVERIFIED"
        and row["verdict"] == "HALLUCINATED"
        for row in completed
    )

    missed_hallucinated = sum(
        row["expected_verdict"] == "HALLUCINATED"
        and row["verdict"] != "HALLUCINATED"
        for row in completed
    )

    false_hallucination_rate = safe_divide(
        false_hallucinated,
        real_reports,
    )

    hallucination_recall = safe_divide(
        correctly_detected_hallucinated,
        hallucinated_reports,
    )

    hallucination_precision = safe_divide(
        correctly_detected_hallucinated,
        predicted_hallucinated,
    )

    # --------------------------------------------------
    # 4. Per-tier and per-repository accuracy
    # --------------------------------------------------

    tier_groups = defaultdict(list)
    repo_groups = defaultdict(list)

    for row in completed:
        tier = row.get("tier") or "unknown"
        repo = row.get("repo") or "unknown"

        tier_groups[str(tier)].append(row)
        repo_groups[str(repo)].append(row)

    per_tier = calculate_group_accuracy(tier_groups)
    per_repository = calculate_group_accuracy(repo_groups)

    # --------------------------------------------------
    # 5. Simplified classification cost
    # --------------------------------------------------

    classification_cost = (
        FALSE_DISMISSAL_COST * false_hallucinated
        + MISSED_HALLUCINATION_COST * missed_hallucinated
    )

    mean_classification_cost = safe_divide(
        classification_cost,
        completed_count,
    )

    # --------------------------------------------------
    # 6. Resource usage
    # --------------------------------------------------

    mean_tool_calls = calculate_mean(
        completed,
        "tool_calls",
    )

    mean_tokens = calculate_mean(
        completed,
        "tokens",
    )

    mean_latency_s = calculate_mean(
        completed,
        "latency_s",
    )

    # --------------------------------------------------
    # 7. Final metrics
    # --------------------------------------------------

    return {
        # Execution statistics
        "total": total,
        "completed": completed_count,
        "skipped": status_counts["skipped"],
        "errors": status_counts["error"],

        # Overall metrics
        "correct": correct,
        "accuracy": safe_divide(correct, completed_count),
        "coverage": safe_divide(completed_count, total),

        # Classification metrics
        "confusion_matrix": confusion,
        "per_class": per_class,
        "macro_f1": macro_f1,

        # Hallucination-specific metrics
        "real_reports": real_reports,
        "hallucinated_reports": hallucinated_reports,
        "false_hallucinated": false_hallucinated,
        "false_hallucination_rate": false_hallucination_rate,
        "missed_hallucinated": missed_hallucinated,
        "hallucination_recall": hallucination_recall,
        "hallucination_precision": hallucination_precision,

        # Dataset breakdowns
        "per_tier": per_tier,
        "per_repository": per_repository,

        # Cost metrics
        "classification_cost": classification_cost,
        "mean_classification_cost": mean_classification_cost,

        # Resource metrics
        "mean_tool_calls": mean_tool_calls,
        "mean_tokens": mean_tokens,
        "mean_latency_s": mean_latency_s,
    }
