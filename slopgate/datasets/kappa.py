"""Inter-annotator agreement for dataset labels (D2 double-labelling).

Each annotator writes one label file, e.g. corpus/d2/labels_pilot.json:

    {"annotator": "pilot", "labels": [{"id": "d2-h1-2298307", "gold": "NOT_HALLUCINATED"}, ...]}

    python -m slopgate.datasets.kappa corpus/d2/labels_pilot.json corpus/d2/labels_b.json [--json]

Reports, over the ids every file labels: raw agreement, Cohen's kappa for each pair of annotators,
Fleiss' kappa when there are three or more, the confusion table for each pair, and every disagreement.
Kappa is None when chance agreement is 1 (every annotator used the same single label): it is undefined
there, and raw agreement is the number to quote. With skewed labels (D2 is 16 vs 2) kappa moves a lot
on one flipped item, so always quote raw agreement next to it."""
import argparse
import itertools
import json
import os
import re
from collections import Counter


class LabelError(ValueError):
    pass


def load_labels(path):
    """-> (annotator name, {id: label}). Duplicate ids and empty labels are errors."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data["labels"] if isinstance(data, dict) else data
    name = data.get("annotator") if isinstance(data, dict) else None
    out = {}
    for r in rows:
        if not isinstance(r, dict):
            raise LabelError("%s: label row is not an object: %r" % (path, r))
        rid, lab = r.get("id"), r.get("gold", r.get("label"))
        if not rid or not lab:
            raise LabelError("%s: row without id or label: %r" % (path, r))
        if rid in out:
            raise LabelError("%s: duplicate id %s" % (path, rid))
        out[rid] = re.sub(r"[\s-]+", "_", str(lab).strip()).upper()   # "not hallucinated" == NOT_HALLUCINATED
    return name or os.path.splitext(os.path.basename(path))[0], out


def cohen_kappa(a, b):
    """Cohen's kappa for two equal-length label sequences; None when chance agreement is 1."""
    if len(a) != len(b):
        raise ValueError("label sequences differ in length")
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


def fleiss_kappa(rows):
    """Fleiss' kappa; rows = one list of labels per item, same number of raters on every item."""
    if not rows:
        return None
    m = len(rows[0])
    if m < 2 or any(len(r) != m for r in rows):
        raise ValueError("every item needs the same number (>= 2) of ratings")
    n = len(rows)
    cats = sorted({x for r in rows for x in r})
    counts = [Counter(r) for r in rows]
    p_bar = sum((sum(c[k] ** 2 for k in cats) - m) / (m * (m - 1)) for c in counts) / n
    pj = [sum(c[k] for c in counts) / (n * m) for k in cats]
    pe = sum(p ** 2 for p in pj)
    if pe >= 1.0:
        return None
    return (p_bar - pe) / (1 - pe)


def agreement(files):
    """files: list of (annotator, {id: label}) -> summary dict."""
    if len(files) < 2:
        raise LabelError("need at least two label files")
    names = [n for n, _ in files]
    if len(set(names)) != len(names):
        raise LabelError("annotator names must be distinct: %s" % names)
    all_ids = set().union(*(set(lab) for _, lab in files))
    common = sorted(set.intersection(*(set(lab) for _, lab in files)))
    missing = {n: sorted(all_ids - set(lab)) for n, lab in files if all_ids - set(lab)}
    labels = sorted({lab[i] for _, lab in files for i in common})

    pairs = []
    for (na, la), (nb, lb) in itertools.combinations(files, 2):
        a, b = [la[i] for i in common], [lb[i] for i in common]
        pairs.append({
            "a": na, "b": nb,
            "agreement": (sum(x == y for x, y in zip(a, b)) / len(common)) if common else None,
            "kappa": cohen_kappa(a, b),
            "confusion": {x: {y: sum(1 for p, q in zip(a, b) if p == x and q == y) for y in labels}
                          for x in labels},
        })
    rows = [[lab[i] for _, lab in files] for i in common]
    disagreements = [{"id": i, "labels": dict(zip(names, r))} for i, r in zip(common, rows) if len(set(r)) > 1]
    return {
        "annotators": names, "n_items": len(common), "labels": labels, "missing": missing,
        "agreement": (1 - len(disagreements) / len(common)) if common else None,
        "pairs": pairs,
        "fleiss_kappa": fleiss_kappa(rows) if len(files) >= 3 else None,
        "label_counts": {n: dict(Counter(lab[i] for i in common)) for n, lab in files},
        "disagreements": disagreements,
    }


def _fmt(x):
    return "undefined" if x is None else "%.3f" % x


def render(s):
    out = ["%d items labelled by all of: %s" % (s["n_items"], ", ".join(s["annotators"]))]
    for n, ids in s["missing"].items():
        out.append("  %s is missing %d id(s): %s" % (n, len(ids), ", ".join(ids)))
    out.append("raw agreement (all annotators): %s" % _fmt(s["agreement"]))
    for p in s["pairs"]:
        out.append("\n%s vs %s: agreement %s, Cohen's kappa %s" % (p["a"], p["b"], _fmt(p["agreement"]), _fmt(p["kappa"])))
        out.append("  rows = %s, columns = %s" % (p["a"], p["b"]))
        w = max(len(x) for x in s["labels"]) if s["labels"] else 0
        out.append("  %-*s  %s" % (w, "", "  ".join("%*s" % (len(y), y) for y in s["labels"])))
        for x in s["labels"]:
            out.append("  %-*s  %s" % (w, x, "  ".join("%*d" % (len(y), p["confusion"][x][y]) for y in s["labels"])))
    if s["fleiss_kappa"] is not None or len(s["annotators"]) >= 3:
        out.append("\nFleiss' kappa: %s" % _fmt(s["fleiss_kappa"]))
    for n, c in s["label_counts"].items():
        out.append("%s label counts: %s" % (n, ", ".join("%s %d" % kv for kv in sorted(c.items()))))
    out.append("\n%d disagreement(s)" % len(s["disagreements"]))
    for d in s["disagreements"]:
        out.append("  %s  %s" % (d["id"], "  ".join("%s=%s" % kv for kv in d["labels"].items())))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+", help="two or more label files")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    a = ap.parse_args(argv)
    try:
        s = agreement([load_labels(p) for p in a.files])
    except (LabelError, OSError, json.JSONDecodeError, KeyError) as e:
        ap.error(str(e))
    print(json.dumps(s, indent=1) if a.json else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
